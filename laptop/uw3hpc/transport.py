"""ssh and rsync to the sites: fixed argv, the authentication lockout, and one login at a time until one works."""
import contextlib
import os
import re
import time

from . import util
from .sites import ADMIN, DENIED, QFAIL, RSYNC, SITES, SSH, SSH_ADD
from .util import Refuse, clean, locked, need, q, untrusted, write_private

WHEEL_OK = set()
AUTH_OK = set()
# ssh's own INFO and VERBOSE lines (OpenSSH 10.3 sshconnect.c, sshconnect2.c, clientloop.c; "Server accepts key", which
# names the key file, is only debug there), dropped before Claude or a log sees stderr.
CHATTER = re.compile(r"^(Authenticated (to|using) |Transferred: sent |Bytes per second: |Server accepts key: "
                     r"|Learned new hostkey: |Deprecating obsolete hostkey: |Killed by signal |\*\* (WARNING: "
                     r"connection is not using a post-quantum|This session may be vulnerable|The server may need to be "
                     r"upgraded)).*\n?", re.M)


def lockfile(site):
    return "%s/%s.locked" % (util.CACHE, site)


def ssh_argv(s):
    # -F none: ~/.ssh/config (ProxyCommand, LocalCommand, Include, forwarding) must not change the connection.
    # VERBOSE: only then does ssh log "Authenticated to", which tells a real refusal from a printed one (own_lines).
    # UpdateHostKeys is on by default with -F none: the server could rewrite ~/.ssh/known_hosts, and at VERBOSE ssh
    # names that file and the new key's fingerprint on stderr.
    opts = ("BatchMode=yes", "IdentitiesOnly=yes", "StrictHostKeyChecking=yes", "UpdateHostKeys=no",
            "ControlMaster=no", "ControlPath=none", "ForwardAgent=no", "ForwardX11=no", "ClearAllForwardings=yes",
            "ConnectTimeout=15", "ServerAliveInterval=15", "ServerAliveCountMax=3", "LogLevel=VERBOSE")
    return [SSH, "-F", "none", "-i", s["key"]] + [x for o in opts for x in ("-o", o)] + ["-l", s["user"]]


def key_test(site, s=None):
    """The publickey-only login that shows a key works before a lock is cleared: no password fallback to hide it."""
    s = s or {}
    return "ssh -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -i %s %s@%s true" % (
        s.get("key") or "<key>", s.get("user") or "<user>", SITES[site]["login"])


def own_lines(err, host):
    """(logged in?, stderr without ssh's own lines). ssh writes "Authenticated to HOST (" before the remote side can
    write anything, and the remote side can add text but not remove it; what comes before is ssh's and the banner.
    Not anchored to a line start: ssh prints the banner as sent, so one without a final newline runs into ssh's line."""
    m = re.search(r"Authenticated to %s \(.*\n?" % re.escape(host), err)
    return m is not None, CHATTER.sub("", err[m.end():] if m else err)


def auth_check(site, s, rc, err, host, authed):
    # Only our own ssh's refusal (exit 255, "user@host:"), not a remote git's "git@github.com: Permission denied", and
    # never after a login: a login profile the remote account controls can print the same line and exit 255. Before
    # a login only ssh and the banner write, so no line-start anchor (see own_lines).
    hit = not authed and rc in (12, 255) and re.search("%s@%s: %s" % (re.escape(s["user"]), re.escape(host),
                                                                    DENIED.pattern), err)
    if hit:
        # Pawsey blocks the address after repeated failures, so one failure stops every later try.
        # Only the matched words: the rest of stderr can come from the remote and is replayed on every refusal.
        write_private(lockfile(site), "%s %s)\n" % (time.strftime("%Y-%m-%d %H:%M"), hit.group(0)))
        raise Refuse("authentication to %s failed, so %s is now locked (%s). Fix the key in a terminal (loaded? "
                     "registered with the site?) and check it with `%s`, then run `/usr/bin/python3 -I %s reset %s`."
                     % (host, site, SITES[site]["lockout"], key_test(site, s), util.INSTALLED, site))
    # After a login the host key was good: this is a remote ssh's, e.g. a git clone from an unknown host.
    need(authed or not rc or "Host key verification failed" not in err, "the host key of %s is unknown or changed. In "
         "a terminal run `ssh %s` once and check the fingerprint against the facility's." % (host, host))


def check_lock(site):
    with contextlib.suppress(FileNotFoundError), open(lockfile(site)) as f:
        raise Refuse("%s is locked after an authentication failure (%s). Fix the key, then run `/usr/bin/python3 -I "
                     "%s reset %s` in a terminal." % (site, clean(f.read(), 200).strip(), util.INSTALLED, site))


def prepare(site, cfg, ctx):
    """Before any connection: lockout, key loaded in the agent, and no sudo on the Kaiju account."""
    check_lock(site)
    key = cfg["sites"][site]["key"]
    need(os.path.isfile(key) and os.path.isfile(key + ".pub"), "key %s or its .pub not found: fix key for %s in "
         "the config" % (key, site))
    # Never --apple-use-keychain: a key that loads itself lets Claude connect while the member is away.
    need(util.run_cmd([SSH_ADD, "-T", key + ".pub"], timeout=15, ctx=ctx)[0] == 0, "the %s key is not loaded: run "
         "`ssh-add -t 12h %s` in a terminal, then try again" % (site, key))
    if site == "kaiju" and site not in WHEEL_OK:
        rc, out, err = ssh(site, cfg, "id -Gn", ctx=ctx)
        need(rc == 0 and "wheel" not in out.split(), "your Kaiju account is in wheel (sudo) or its groups could "
             "not be read; Claude must not drive an account with sudo. Use site kaiju-agent." + untrusted(out + err))
        WHEEL_OK.add(site)


def connect(site, s, argv, host, **kw):
    """Until a login to the site has worked in this process, logins go one at a time across sessions and each
    rechecks the lockout, so parallel unprompted calls cannot send Pawsey a burst of failures."""
    with contextlib.nullcontext() if site in AUTH_OK else locked(site + ".auth"):
        check_lock(site)
        rc, out, err = util.run_cmd(argv, **kw)
        authed, shown = own_lines(err, host)
        auth_check(site, s, rc, err, host, authed)
    if authed or rc not in (12, 255):
        AUTH_OK.add(site)
    return rc, out, shown, authed


def ssh(site, cfg, inner, args=(), data=None, ctx=None):
    # A login bash puts qsub/sbatch/module on PATH; timeout keeps us inside login-node CPU limits.
    h, words = SITES[site]["login"], ["timeout", str(ADMIN["remote_s"]), "bash", "-lc", q(inner)]
    words += ["hpc"] + [q(a) for a in args] if args else []
    rc, out, err, authed = connect(site, cfg["sites"][site], ssh_argv(cfg["sites"][site]) + ["--", h, " ".join(words)],
                                   h, data=data, timeout=ADMIN["ssh_s"], ctx=ctx)
    need(rc != 255, ("the session on %s ended with exit 255 after logging in (connection dropped, or the login profile "
                     "or command exited 255)." if authed else "could not reach %s (network or VPN?).") % h
         + untrusted(clean(err, 300), site))
    return rc, out, err


def remote_text(site, cfg, ctx, inner):
    prepare(site, cfg, ctx)
    rc, out, err = ssh(site, cfg, inner, ctx=ctx)
    return out + (err if rc else "") + ("\n" + QFAIL if rc == 124 else "")


def rsync(site, s, src, dst, ctx, opts, tick):
    argv = [RSYNC] + opts + ["--timeout=120", "-e", " ".join(q(a) for a in ssh_argv(s) + ["--"]), "--", src, dst]
    rc, out, err, _ = connect(site, s, argv, SITES[site]["copy"], ctx=ctx, tick=tick)
    need(rc in (0, 23, 24), "rsync with %s failed (exit %d)." % (SITES[site]["copy"], rc) + untrusted(err, site))
    return rc
