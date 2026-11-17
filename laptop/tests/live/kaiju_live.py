#!/usr/bin/python3 -I
"""Live tests, part 1: your own Kaiju account, through this checkout's server over JSON-RPC, as Claude Code drives it.
Kaiju only, never Gadi or Setonix: Pawsey blocks an address after failed logins.

  /usr/bin/python3 -I tests/live/kaiju_live.py [--dry-run] [--steps abcde] [--config PATH] [--results FILE]

Run it yourself in a terminal. It asks y/N before every step that reaches Kaiju and writes each step's outcome to
FILE (default tests/live/results/kaiju-<time>.json, git-ignored) as it goes. It uses your real config, keys and ssh
agent (load the Kaiju key first: ssh-add -t 12h KEY), except step e. b to d need the managed settings file in place
(the server refuses every call without it). --dry-run prints every step and the exact tool calls, and starts nothing.

  a  doctor, for information only: ~/.local/share/uw3-hpc is still the previous release until you install this one.
  b  status on kaiju. An account in wheel is refused, by design: c is then skipped.
  c  put a tiny run folder, run "echo ok", submit a 1-core 2-minute job, wait, get, and check the job's output.
  d  you put a one-shot line at the top of your Kaiju ~/.bashrc that prints "<you>@kaiju.anu.edu.au: Permission
     denied (publickey)." and exits 255. A fresh server's first login (the wheel check, so it works for wheel
     accounts too) meets it: Kaiju must NOT lock, and a status afterwards must not say locked. Then you remove it.
  e  one deliberately refused login: a fresh throwaway key that Kaiju never registered, loaded only into a temp
     ssh-agent, with a temp config and a separate --home, so your real lock state is untouched. kaiju MUST lock
     there; then reset (you type yes) must clear it.

Open live tests in ADMIN.md this covers:
  1  partly: openrsync put and get against Kaiju; not gadi-dm or data-mover, nor a hostile agent-side sender.
  2  partly: bash -lc finds sbatch over ssh, on Kaiju only.
  4  partly: whether Kaiju's job-end email arrives (c asks you).
  8  partly: a wait with progress notifications; not Claude Code's background and Esc handling, nor Gadi's floor.
  10 the own-account half: the lockout (d, e). Not covered: 3 (Gadi), 7 (a UW3 build within run's 120 s), 9 and 11
  (need Claude Code itself), 12 (Kaiju's policy helper), and 5, 6 and the agent half of 10 (part 2).

Part 2, a sketch (not built): the same driver against site kaiju-agent, for a member who has an agent account.
  - status kaiju-agent: fixed fields only; task with a tiny prompt ("write SUMMARY.md saying hello"); wait; get the
    outbox; a second, long task, then cancel; print the resume command and try it by hand (open tests 5 and 6).
  - The case this lockout fix is for: step d's line in the agent's ~/.bashrc (root owns it, so the admin puts it
    there); status and get on kaiju-agent must NOT lock and must not echo the text; then restore ~/.bashrc.
  - The hostile sender (rest of open test 1): the agent's ~/.bashrc prints junk to stdout; get must fail cleanly.
"""
import json
import os
import pwd
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

CHECKOUT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
ENTRY = os.path.join(CHECKOUT, "hpc_mcp.py")
sys.path.append(CHECKOUT)
sys.dont_write_bytecode = True
from uw3hpc import VERSION, admin, config, sites, util  # noqa: E402 (needs CHECKOUT on sys.path)

SITE = "kaiju"
HOST = sites.SITES[SITE]["login"]
REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir
# As the member registers it (admin.REGISTER): nothing inherited, so serve finds the login ssh agent itself.
SERVE = ["/usr/bin/env", "-i", "/usr/bin/python3", "-I", ENTRY, "serve"]
JOB = '#!/bin/bash\necho "uw3hpc live ok job=$SLURM_JOB_ID host=$(hostname)" > result.txt\n'
FLAG = "~/.uw3hpc-deny-once"
WHEEL = "is in wheel (sudo)"


class Results:
    def __init__(self, path):
        self.path, self.data = path, {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "checkout": CHECKOUT,
                                      "version": VERSION, "release_sha256": admin.release(CHECKOUT), "steps": []}
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def add(self, step, what, outcome, detail="", call=None, t0=None):
        self.data["steps"].append({"step": step, "what": what, "outcome": outcome, "call": call,
                                   "seconds": round(time.time() - t0, 1) if t0 else None,
                                   "detail": util.clean(str(detail), 3000)})
        print("%-4s %s %s%s" % (outcome, step, what, "" if outcome in ("PASS", "SKIP") else "\n     " + util.clean(
            str(detail), 600).replace("\n", "\n     ")), flush=True)
        with open(self.path + ".tmp", "w") as f:
            json.dump(self.data, f, indent=1)
        os.replace(self.path + ".tmp", self.path)


class Server:
    """One serve process and a JSON-RPC client for it; progress notifications are printed as they come."""

    def __init__(self, argv, env=None, cwd=None, log=None):
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd, env=env,
                                  stderr=open(log, "ab") if log else subprocess.DEVNULL)
        self.lines, self.n = queue.Queue(), 0
        threading.Thread(target=lambda: [self.lines.put(x) for x in self.p.stdout], daemon=True).start()
        r = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "kaiju-live", "version": "1"}}, 30)
        self.info = (r.get("result") or {}).get("serverInfo") or {}
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, msg):
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()

    def request(self, method, params, timeout):
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = json.loads(self.lines.get(timeout=max(0.1, end - time.time())))
            except queue.Empty:
                break
            if msg.get("method") == "notifications/progress":
                print("     progress: %s" % msg["params"].get("message"), flush=True)
            elif msg.get("id") == self.n:
                return msg
        self.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": self.n}})
        return {"error": {"message": "no reply in %d s (cancelled)" % timeout}}

    def call(self, name, args, timeout=300):
        """(text, isError)"""
        assert args.get("site", SITE) == SITE, "this kit drives Kaiju only"
        r = self.request("tools/call", {"name": name, "arguments": args, "_meta": {"progressToken": self.n + 1}},
                         timeout)
        res = r.get("result") or {}
        return ((res.get("content") or [{}])[0].get("text", "") or json.dumps(r.get("error")), res.get("isError", True))

    def close(self):
        if self.p.poll() is None:
            self.p.stdin.close()
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()


def ask(question):
    try:
        return input("\n%s [y/N] " % question).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def lock_of(home):
    return os.path.join(home, ".cache/uw3-hpc/%s.locked" % SITE)


def bashrc_line(user):
    """Prints the refusal and exits 255 once: the first login after the flag file appears removes it."""
    return ("[ -e %s ] && { rm -f %s; printf '%%s@%%s: Permission denied (publickey).\\n' %s %s >&2; exit 255; }"
            % (FLAG, FLAG, user, HOST))


def plan(cfg, run):
    """Every step and its tool calls, as (step, what, tool or None, arguments)."""
    user = cfg["user"] if cfg else "<kaiju user from your config>"
    up = "%s/%s/%s" % (cfg["uploads"] if cfg else "<uploads>", SITE, run)
    return [
        ("a", "doctor (information only)", None, ["/usr/bin/python3", "-I", ENTRY, "doctor"]),
        ("b", "status", "status", {"site": SITE}),
        ("c1", "put a tiny run folder (%s/job.sh)" % up, "put", {"site": SITE, "run": run}),
        ("c2", 'run "echo ok"', "run", {"site": SITE, "run": run, "command": "echo ok"}),
        ("c3", "submit a 1-core 2-minute job", "submit", {"site": SITE, "run": run, "total_core_hours": 1, "jobs": [
            {"script": "job.sh", "walltime": "00:02:00", "cores": 1}]}),
        ("c4", "wait for it", "wait", {"site": SITE, "id": "<job id from c3>", "max_minutes": 15}),
        ("c5", "get the run", "get", {"site": SITE, "run": run}),
        ("c6", "check the job's result.txt in the folder c5 names", None, "local: no connection"),
        ("c7", "ask you whether Kaiju's job-end email arrived (open test 4)", None, "local: no connection"),
        ("d0", "you, in a terminal on Kaiju: put this line at the very top of ~/.bashrc, then touch %s" % FLAG, None,
         bashrc_line(user)),
        ("d1", "a fresh server's first login meets the line, a printed refusal and exit 255 after a real login: must "
               "NOT lock", "run", {"site": SITE, "run": run, "command": "true"}),
        ("d2", "status afterwards: never locked (refused only for an account in wheel)", "status", {"site": SITE}),
        ("d3", "you remove the line from ~/.bashrc", None, "local: no connection"),
        ("e1", "one refused login (throwaway key, temp agent, temp --home): MUST lock", "status", {"site": SITE}),
        ("e2", "while locked: refused before any connection", "status", {"site": SITE}),
        ("e3", "reset kaiju --home <temp> (you type yes): clears the lock", None,
         ["/usr/bin/python3", "-I", ENTRY, "reset", SITE, "--home", "<temp home>"])]


def dry_run(cfg, run, steps, cfgpath):
    print("Dry run: nothing is started and nothing connects.\nServer: %s%s\n" % (" ".join(SERVE), (
        " --config " + cfgpath) if cfgpath else ""))
    print("Step e's server: /usr/bin/env -i SSH_AUTH_SOCK=agent.sock /usr/bin/python3 -I %s serve --home <temp home> "
          "(cwd: the temp folder holding the throwaway key and agent.sock)\n" % ENTRY)
    for step, what, tool, args in plan(cfg, run):
        if step[0] in steps:
            print("%-3s %s\n    %s" % (step, what, "tools/call " + json.dumps({"name": tool, "arguments": args})
                                       if tool else args if isinstance(args, str) else " ".join(args)))
    return 0


def main(argv):
    opts = {a: b for a, b in zip(argv, argv[1:]) if a in ("--steps", "--config", "--results")}
    if [a for i, a in enumerate(argv) if a not in opts and a != "--dry-run" and (i == 0 or argv[i - 1] not in opts)]:
        return print(__doc__.strip()) or 2
    steps, cfgpath = opts.get("--steps", "abcde"), opts.get("--config")
    run = "uw3hpc-live-" + time.strftime("%Y%m%d-%H%M%S")
    if "--dry-run" in argv:
        cfg = None
        if cfgpath:  # only a config named on the command line: a dry run reads nothing of yours by default
            util.set_home(REAL_HOME)
            cfg = config.load_config(cfgpath)["sites"].get(SITE)
        return dry_run(cfg, run, steps, cfgpath)
    if not sys.stdin.isatty():
        return print("Run this in a terminal: it asks before every step that reaches Kaiju.") or 2
    util.set_home(REAL_HOME)
    cfg = config.load_config(cfgpath or util.CONFIG)["sites"].get(SITE)
    if not cfg:
        return print("No kaiju site in %s." % (cfgpath or util.CONFIG)) or 2
    res = Results(opts.get("--results") or os.path.join(os.path.dirname(os.path.realpath(__file__)), "results",
                                                         "kaiju-%s.json" % time.strftime("%Y%m%d-%H%M%S")))
    print("Checkout %s, server %s. Results go to %s" % (CHECKOUT, VERSION, res.path))
    calls = {s: (t, a) for s, _, t, a in plan(cfg, run)}
    if os.path.exists(lock_of(REAL_HOME)):
        return print("kaiju is locked already (%s): clear it with `reset kaiju` first." % lock_of(REAL_HOME)) or 1
    gate = admin.managed_gate()  # the server would refuse every call in b to d
    if gate and set(steps) & set("bcd"):
        res.add("-", "managed settings file in place for b, c and d", "FAIL", gate)
        steps = "".join(x for x in steps if x not in "bcd")
    if "a" in steps:
        t0 = time.time()
        p = subprocess.run(calls["a"][1], capture_output=True, text=True, timeout=120)
        res.add("a", "doctor (information only)", "INFO", "exit %d\n%s" % (p.returncode, p.stdout + p.stderr),
                calls["a"][1], t0)
    srv = None
    try:
        if set(steps) & set("bc"):
            srv = Server(SERVE + (["--config", cfgpath] if cfgpath else []), log=res.path + ".server.err")
            res.add("-", "server started: %s" % json.dumps(srv.info), "PASS" if srv.info.get("version") == VERSION
                    else "FAIL", srv.info)
        if "b" in steps:
            text = step(res, srv, "b", "status", calls, lambda t, e: not e or WHEEL in t)
            if text and WHEEL in text:
                res.add("c", "put, run, submit, wait, get", "SKIP", "your Kaiju account is in wheel, so every tool "
                        "refuses it by design; d and e still run")
                steps = steps.replace("c", "")
        if "c" in steps:
            run_folder(res, srv, cfg, run, calls, steps)
    finally:
        if srv:
            srv.close()
    if "d" in steps:
        printed_refusal(res, cfg, calls, cfgpath)
    if "e" in steps:
        refused_login(res, cfg, calls)
    print("\nDone. Results: %s" % res.path)
    if "c" in steps:
        print("Left in place: %s/%s on Kaiju, and the local uploads and downloads copies." % (cfg["base"], run))
    return 1 if any(s["outcome"] == "FAIL" for s in res.data["steps"]) else 0


def step(res, srv, name, what, calls, ok, args=None, timeout=300):
    tool, a = calls[name][0], args or calls[name][1]
    if not ask("%s: %s %s reaches Kaiju. Go ahead?" % (name, tool, json.dumps(a))):
        res.add(name, what, "SKIP", "not confirmed", {"name": tool, "arguments": a})
        return None
    t0 = time.time()
    text, err = srv.call(tool, a, timeout)
    res.add(name, what, "PASS" if ok(text, err) else "FAIL", text, {"name": tool, "arguments": a}, t0)
    return text


def printed_refusal(res, cfg, calls, cfgpath):
    """d: a login profile that prints the refusal after a real login. A fresh server, so its first kaiju login is the
    wheel check, which every account makes and no cached listing answers."""
    print("\nd0: in a terminal, ssh kaiju, put this line at the very top of ~/.bashrc (above any early return for "
          "non-interactive shells), then run: touch %s\n\n    %s\n" % (FLAG, bashrc_line(cfg["user"])))
    if not ask("d0: is the line at the top of ~/.bashrc, and %s created? (no connection)" % FLAG):
        return res.add("d", "printed refusal after login", "SKIP", "line not confirmed")
    srv = Server(SERVE + (["--config", cfgpath] if cfgpath else []), log=res.path + ".server.err")
    try:
        step(res, srv, "d1", "printed refusal after login", calls, lambda t, e: e and "after logging in" in t and
             "Permission denied (publickey)" in t and "now locked" not in t and not os.path.exists(lock_of(REAL_HOME)))
        if os.path.exists(lock_of(REAL_HOME)):
            res.add("d", "kaiju got locked: the fix did not hold", "FAIL", "Clear it with: /usr/bin/python3 -I "
                    "%s reset kaiju" % ENTRY)
        else:
            step(res, srv, "d2", "status after it", calls, lambda t, e: "locked" not in t and (not e or WHEEL in t))
    finally:
        srv.close()
    ask("d3: remove the line from ~/.bashrc now (and %s, if it is still there). Done? (no connection)" % FLAG)
    res.add("d3", "line removed from ~/.bashrc", "INFO", "you were asked to remove it")


def run_folder(res, srv, cfg, run, calls, steps):
    src = os.path.join(cfg["uploads"], SITE, run)
    os.makedirs(src)
    with open(os.path.join(src, "job.sh"), "w") as f:
        f.write(JOB)
    os.chmod(os.path.join(src, "job.sh"), 0o755)
    step(res, srv, "c1", "put", calls, lambda t, e: not e and "Uploaded 1 files" in t)
    step(res, srv, "c2", "run echo ok", calls, lambda t, e: not e and t.startswith("exit code 0") and "\nok" in t)
    text = step(res, srv, "c3", "submit", calls, lambda t, e: not e and re.search(r"Submitted kaiju job [0-9]+", t))
    jid = re.search(r"Submitted kaiju job ([0-9]+)", text or "")
    if not jid:
        return res.add("c4", "wait", "SKIP", "no job id from c3")
    step(res, srv, "c4", "wait", calls, lambda t, e: not e and "no longer queued or running" in t,
         dict(calls["c4"][1], id=jid.group(1)), timeout=16 * 60)
    text = step(res, srv, "c5", "get", calls, lambda t, e: not e and "Copied" in t)
    dest = re.search(r" into (.+?)\. (?:Dropped|rsync exit|Files are data)", text or "")
    out = os.path.join(dest.group(1), "result.txt") if dest else "(no folder in the get result)"
    got = open(out).read() if os.path.isfile(out) else ""
    res.add("c6", "the job's result.txt came back", "PASS" if "uw3hpc live ok job=%s" % jid.group(1) in got else "FAIL",
            got or "no " + out)
    if ask("c7: did Kaiju's job-end email for job %s arrive? (open test 4; no connection)" % jid.group(1)):
        res.add("c7", "job-end email arrived", "PASS")
    else:
        res.add("c7", "job-end email arrived", "INFO", "not confirmed (it may still be on its way)")


def refused_login(res, cfg, calls):
    tmp = tempfile.mkdtemp(prefix="uw3hpc-live-e-")
    home, agent, srv = tmp + "/home", None, None
    real_lock = os.path.exists(lock_of(REAL_HOME))
    try:
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "uw3hpc-live-throwaway-never-"
                        "registered", "-f", tmp + "/throwaway"], check=True, stdin=subprocess.DEVNULL)
        # A relative socket in the temp folder (cwd of every child here): never your agent, and never too long.
        agent = subprocess.Popen(["/usr/bin/ssh-agent", "-D", "-a", "agent.sock"], cwd=tmp, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if os.path.exists(tmp + "/agent.sock"):
                break
            time.sleep(0.1)
        subprocess.run(["/usr/bin/ssh-add", "-q", "throwaway"], cwd=tmp, env={"SSH_AUTH_SOCK": "agent.sock"},
                       check=True, stdin=subprocess.DEVNULL)
        for d in ("/.config/uw3-hpc", "/hpc/downloads", "/hpc/uploads"):
            os.makedirs(home + d, mode=0o700)
        for d in ("downloads", "uploads"):
            open("%s/hpc/%s/%s" % (home, d, sites.MARKER), "w").close()
        util.write_private(home + "/.config/uw3-hpc/config.json", json.dumps({"sites": {SITE: {
            "user": cfg["user"], "key": tmp + "/throwaway", "base": cfg["base"]}}}))
        # Under --home serve wants the managed file there, and accepts the account's own copy.
        mdir = os.path.realpath(home) + os.path.dirname(admin.MANAGED)
        os.makedirs(mdir, mode=0o755)
        shutil.copy(os.path.join(CHECKOUT, "managed-settings.json"), mdir)
        os.chmod(os.path.join(mdir, "managed-settings.json"), 0o644)
        if not ask("e1: status on kaiju with a throwaway key Kaiju never registered: ONE failed login to %s as %s. "
                   "Go ahead?" % (HOST, cfg["user"])):
            return res.add("e", "refused login", "SKIP", "not confirmed")
        srv = Server(["/usr/bin/env", "-i", "SSH_AUTH_SOCK=agent.sock", "/usr/bin/python3", "-I", ENTRY, "serve",
                      "--home", home], cwd=tmp, log=tmp + "/server.err")
        t0 = time.time()
        text, err = srv.call(*calls["e1"])
        locked = os.path.exists(lock_of(home))
        res.add("e1", "refused login locks (temp home)", "PASS" if err and "now locked" in text and locked and
                os.path.exists(lock_of(REAL_HOME)) == real_lock else "FAIL", text, dict(
                    zip(("name", "arguments"), calls["e1"])), t0)
        if not locked:
            return res.add("e2", "while locked", "SKIP", "no lock, so a second call would log in again")
        t0 = time.time()
        text, err = srv.call(*calls["e2"])
        res.add("e2", "while locked: refused at once", "PASS" if err and "is locked" in text and time.time() - t0 < 5
                else "FAIL", text, dict(zip(("name", "arguments"), calls["e2"])), t0)
        srv.close()
        print("\ne3: reset asks on this terminal; type yes.")
        rc = subprocess.call(["/usr/bin/python3", "-I", ENTRY, "reset", SITE, "--home", home])
        res.add("e3", "reset clears the lock", "PASS" if rc == 0 and not os.path.exists(lock_of(home)) else "FAIL",
                "reset exit %d" % rc)
    finally:
        for p in (srv and srv.p, agent):
            if p and p.poll() is None:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
