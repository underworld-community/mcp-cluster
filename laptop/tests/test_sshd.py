#!/usr/bin/python3 -I
"""Opt-in: the authentication lockout over a real OpenSSH round trip on this Mac, through the server's own transport
code with the real /usr/bin/ssh and /usr/bin/rsync. It opens a local port, so it runs only with UW3HPC_SSHD_TEST=1
(run_all skips it otherwise).

  UW3HPC_SSHD_TEST=1 /usr/bin/python3 -I tests/test_sshd.py [ROOT]

A non-root /usr/sbin/sshd listens on 127.0.0.1 at a free high port with two temp host keys, UsePAM no, StrictModes no,
a Banner file and an AuthorizedKeysFile holding one throwaway key. Its ForceCommand stands in for the account's login
profile: it prints "<user>@localhost: Permission denied (publickey)." and exits 255, or answers normally. The keys
live in a temp ssh-agent, never the member's; known_hosts is a temp file holding one of the two host keys, so the
server offers ssh a key to add. Everything started is killed at the end. If sshd will not run unprivileged, the test
says so and exits 0: the harness's fakes still cover the logic.
"""
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import time

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import testkit  # noqa: E402 (needs the path above)

if os.environ.get("UW3HPC_SSHD_TEST") != "1":
    print("SKIP test_sshd: set UW3HPC_SSHD_TEST=1 to run it (it opens a port on 127.0.0.1)")
    sys.exit(0)

ROOT = testkit.use(sys.argv[1] if len(sys.argv) > 1 else None)
from uw3hpc import sites, transport, util  # noqa: E402 (needs ROOT on sys.path)

WORK = testkit.workdir("sshd")
ME = pwd.getpwuid(os.getuid()).pw_name
SITE = "kaiju-agent"  # the account whose login profile the agent can rewrite
fails, procs, RAW = [], [], []


def check(label, ok, detail=""):
    print("%s %s%s" % ("PASS" if ok else "FAIL", label, "" if ok else "  -- " + str(detail)[:800]))
    fails.extend([] if ok else [label])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = str(free_port())


class LocalOnly(testkit._Popen):
    """In place of testkit's guard: ssh and rsync may reach localhost on PORT only; scp and sftp never."""

    def __init__(self, args, *a, **kw):
        w = [str(x) for x in (args if isinstance(args, (list, tuple)) else [args])]
        name, at = os.path.basename(w[0]), lambda k: w[w.index(k) + 1] if k in w else ""
        ok = {"ssh": lambda: at("--") == "localhost" and at("-p") == PORT,
              "rsync": lambda: " -p %s " % PORT in at("-e") and any(x.startswith("localhost:") for x in w[-2:]),
              "scp": lambda: False, "sftp": lambda: False}.get(name, lambda: True)
        if not ok():
            raise RuntimeError("local-only guard refused %r" % w[:3])
        super().__init__(args, *a, **kw)


subprocess.Popen = LocalOnly


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, **kw)


def start():
    """sshd and the agent, or the reason sshd will not run."""
    for k, t in (("hostkey", "ed25519"), ("hostkey2", "ecdsa"), ("good", "ed25519"), ("bad", "ed25519")):
        run(["/usr/bin/ssh-keygen", "-q", "-t", t, "-N", "", "-C", "uw3hpc-sshd-test-throwaway", "-f",
             WORK + "/" + k]).check_returncode()
    banner("")
    shutil.copy(WORK + "/good.pub", WORK + "/authorized")
    with open(WORK + "/remote.sh", "w") as f:  # the stand-in login profile, run by sshd through your shell's -c
        f.write('#!/bin/bash\nmode=$(cat "%s/mode")\n'
                'if [ "$mode" = profile ]; then printf "%%s@localhost: Permission denied (publickey).\\n" '
                '"$(id -un)" >&2; exit 255; fi\n'
                # slow: time for the server's host-key update to finish before the session ends
                'if [ "$mode" = slow ]; then sleep 1; fi\n'
                'case $SSH_ORIGINAL_COMMAND in "rsync --server "*) exec /bin/bash --noprofile --norc -c '
                '"$SSH_ORIGINAL_COMMAND" ;; esac\necho remote ok; echo remote note >&2\n' % WORK)
    os.chmod(WORK + "/remote.sh", 0o755)
    with open(WORK + "/sshd_config", "w") as f:
        f.write("".join("%s %s\n" % kv for kv in (
            ("ListenAddress", "127.0.0.1:" + PORT), ("HostKey", WORK + "/hostkey"), ("HostKey", WORK + "/hostkey2"),
            ("Banner", WORK + "/banner"), ("PidFile", WORK + "/sshd.pid"),
            ("AuthorizedKeysFile", WORK + "/authorized"), ("AuthorizedKeysCommand", "none"), ("UsePAM", "no"),
            ("StrictModes", "no"), ("PasswordAuthentication", "no"), ("KbdInteractiveAuthentication", "no"),
            ("PermitUserRC", "no"), ("PermitTTY", "no"), ("AllowTcpForwarding", "no"), ("AllowAgentForwarding", "no"),
            ("X11Forwarding", "no"), ("AllowUsers", ME), ("ForceCommand", WORK + "/remote.sh"))))
    t = run(["/usr/sbin/sshd", "-t", "-f", WORK + "/sshd_config"])
    if t.returncode:
        return "sshd -t: " + t.stderr
    procs.append(subprocess.Popen(["/usr/sbin/sshd", "-D", "-f", WORK + "/sshd_config", "-E", WORK + "/sshd.log"],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    # Relative socket: a full path under a long temp folder is over the 104-byte limit; every child shares our cwd.
    os.chdir(WORK)
    procs.append(subprocess.Popen(["/usr/bin/ssh-agent", "-D", "-a", "agent.sock"], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    end = time.time() + 10
    while time.time() < end:
        with socket.socket() as s:
            up = s.connect_ex(("127.0.0.1", int(PORT))) == 0
        if up and os.path.exists("agent.sock") or procs[0].poll() is not None:
            break
        time.sleep(0.2)
    if procs[0].poll() is not None or not up:
        return "sshd did not start: " + (read(WORK + "/sshd.log") or "no log")
    os.environ["SSH_AUTH_SOCK"] = "agent.sock"  # util.child_env passes it on to every child
    for k in ("good", "bad"):
        run(["/usr/bin/ssh-add", "-q", WORK + "/" + k], env={"SSH_AUTH_SOCK": "agent.sock"}).check_returncode()
    with open(WORK + "/hostkey.pub") as f:
        util.write_private(WORK + "/known_hosts", "[localhost]:%s %s\n" % (PORT, " ".join(f.read().split()[:2])))
    return ""


def read(p):
    try:
        with open(p) as f:
            return f.read()
    except OSError:
        return None


def stop():
    for p in procs:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


def main():
    why = ""
    try:
        why = start()
    except (OSError, subprocess.SubprocessError) as e:
        why = "setup failed: %s" % e
    if why:
        stop()
        print("SKIP test_sshd: %s\n(the harness's fakes still cover the lockout)" % why.strip()[:600])
        return 0
    real_argv, real_run, saved = transport.ssh_argv, util.run_cmd, dict(sites.SITES[SITE])
    try:
        util.set_home(WORK + "/home")
        util.ensure_cache()
        sites.SITES[SITE].update(login="localhost", copy="localhost")
        # Only what reaching a test sshd needs; every option the server sets stays as it is.
        transport.ssh_argv = lambda s: real_argv(s) + ["-p", PORT, "-o", "UserKnownHostsFile=" + WORK + "/known_hosts",
                                                       "-o", "GlobalKnownHostsFile=/dev/null", "-o",
                                                       "AddressFamily=inet"]

        def recorded(argv, **kw):
            r = real_run(argv, **kw)
            RAW.append((argv, r))
            return r
        util.run_cmd = recorded
        cases()
    finally:
        transport.ssh_argv, util.run_cmd = real_argv, real_run
        sites.SITES[SITE].update(saved)
        stop()
    print("ALL PASS" if not fails else "%d FAILED" % len(fails))
    return 1 if fails else 0


def mode(m):
    with open(WORK + "/mode", "w") as f:
        f.write(m + "\n")
    transport.AUTH_OK.clear()


def banner(text):
    """sshd reads the Banner file for each connection; an empty one sends nothing."""
    with open(WORK + "/banner", "w") as f:
        f.write(text)


def cases():
    lock, ctx = transport.lockfile(SITE), util.Call()
    os.makedirs(WORK + "/remote/r1")
    with open(WORK + "/remote/r1/out.txt", "w") as f:
        f.write("ok\n")

    def cfg(key):
        return {"sites": {SITE: {"user": ME, "key": WORK + "/" + key}}}

    def raw(n, prog):
        return [r for a, r in RAW[n:] if a[0] == prog]

    def via_ssh(key):
        """The refusal, or "" and what ssh returned to the caller; then the raw (rc, out, err) of each ssh run."""
        n, got = len(RAW), []
        err = util.refusal(lambda: transport.prepare(SITE, cfg(key), ctx) or got.append(transport.ssh(
            SITE, cfg(key), "true", ctx=ctx)))
        return err, got, raw(n, sites.SSH)

    def via_rsync(key, dst):
        n = len(RAW)
        err = util.refusal(transport.rsync, SITE, cfg(key)["sites"][SITE], "localhost:%s/remote/r1/" % WORK,
                           dst + "/", ctx, ["-r"], None)
        return err, raw(n, sites.RSYNC)

    def clean(text):
        return not re.search(r"Authenticated|Transferred:|Bytes per second|SHA256:|127\.0\.0\.1|/good|/bad|quantum",
                             text)

    login = re.compile(r'(?m)^Authenticated to localhost \(\[127\.0\.0\.1\]:%s\) using "publickey"\.\r$' % PORT)
    denial = "%s@localhost: Permission denied (publickey)." % ME

    mode("ok")
    err, got, r = via_ssh("good")
    check("ssh, login works: at LogLevel=VERBOSE ssh writes 'Authenticated to localhost ([127.0.0.1]:PORT) using "
          "\"publickey\".' and the transfer counts; the caller gets the remote's stderr only", not err and r and
          r[0][0] == 0 and login.search(r[0][2]) and "Transferred: sent " in r[0][2] and got and got[0][:2] == (
              0, "remote ok\n") and got[0][2].strip() == "remote note", (err, got, r))
    err, r = via_rsync("good", WORK + "/dl-ok")
    check("openrsync, login works: a real transfer; ssh's lines reach rsync's stderr", not err and r and r[0][0] == 0
          and login.search(r[0][2]) and read(WORK + "/dl-ok/out.txt") == "ok\n", (err, r))

    mode("profile")
    err, got, r = via_ssh("good")
    check("ssh, the login works, then the profile prints the denial and exits 255: NOT locked", r and r[0][0] == 255
          and login.search(r[0][2]) and denial in r[0][2] and "after logging in" in err and not os.path.exists(lock)
          and clean(err), (err, r))
    err, r = via_rsync("good", WORK + "/dl-profile")
    check("openrsync, the same: NOT locked", r and r[0][0] in (12, 255) and login.search(r[0][2]) and denial in r[0][2]
          and "rsync with localhost failed" in err and not os.path.exists(lock) and clean(err), (err, r))
    if os.path.exists(lock):  # so a failure above does not decide the checks below
        os.unlink(lock)

    mode("ok")
    err, got, r = via_ssh("bad")
    check("ssh, the key is really refused: locked, with the fixed words only", r and r[0][0] == 255 and
          not login.search(r[0][2]) and denial in r[0][2] and "now locked" in err and re.fullmatch(
              r"\S+ \S+ %s\)\n" % re.escape(denial[:-2]), read(lock) or ""), (err, r, read(lock)))
    n = len(RAW)
    err = via_ssh("good")[0]
    check("while locked, nothing starts, not even ssh-add", "is locked" in err and len(RAW) == n, err)
    os.unlink(lock)
    err, r = via_rsync("bad", WORK + "/dl-bad")
    check("openrsync, the key is really refused: locked", r and r[0][0] in (12, 255) and not login.search(r[0][2]) and
          denial in r[0][2] and "now locked" in err and os.path.exists(lock), (err, r))
    os.unlink(lock)

    # ssh prints the banner as sent, so one without a final newline runs into ssh's next line.
    glued = "Authorised users only. Activity is logged."
    banner(glued)
    mode("profile")
    err, got, r = via_ssh("good")
    check("banner without a final newline, the login works, then the profile prints the denial and exits 255: NOT "
          "locked, and the banner is not shown", r and r[0][0] == 255 and (glued + "Authenticated to localhost (") in
          r[0][2] and denial in r[0][2] and "after logging in" in err and not os.path.exists(lock) and clean(err) and
          glued not in err, (err, r))
    err, r = via_rsync("good", WORK + "/dl-glued")
    check("openrsync, the same: NOT locked", r and r[0][0] in (12, 255) and (glued + "Authenticated to") in r[0][2] and
          not os.path.exists(lock), (err, r))
    if os.path.exists(lock):
        os.unlink(lock)
    mode("ok")
    err, got, r = via_ssh("bad")
    check("banner without a final newline, the key is really refused: locked", r and r[0][0] == 255 and
          (glued + denial) in r[0][2] and "now locked" in err and os.path.exists(lock), (err, r))
    if os.path.exists(lock):
        os.unlink(lock)
    banner("")

    # The server offers its second host key after a login. -F none would let ssh add it to known_hosts and log the
    # file and the fingerprint at VERBOSE; this test's UserKnownHostsFile turns that default off, so put it back.
    with open(WORK + "/known_hosts") as f:
        before = f.read()
    real_argv = transport.ssh_argv

    def default_on(s):
        a = real_argv(s)
        i = a.index("UpdateHostKeys=no")
        return a[:i - 1] + a[i + 1:] + ["-o", "UpdateHostKeys=yes"]
    mode("slow")
    try:
        transport.ssh_argv = default_on
        err, got, r = via_ssh("good")
        added = read(WORK + "/known_hosts") != before
        with open(WORK + "/known_hosts", "w") as f:
            f.write(before)
        check("control: with ssh's default UpdateHostKeys the server's second key is added to known_hosts, logged with "
              "the file's path", not err and r and added and re.search(r"Learned new hostkey|Adding new key", r[0][2]),
              (err, r))
        transport.ssh_argv = lambda s: real_argv(s) + ["-o", "UpdateHostKeys=yes"]
        err, got, r = via_ssh("good")
        check("the server's own UpdateHostKeys=no wins over that default: known_hosts unchanged, nothing logged",
              not err and r and read(WORK + "/known_hosts") == before and not re.search(
                  r"Learned new hostkey|Adding new key|known_hosts", r[0][2]), (err, r))
    finally:
        transport.ssh_argv = real_argv


if __name__ == "__main__":
    sys.exit(main())
