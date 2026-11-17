"""Plumbing every module shares: refusals, the per-call context, child processes, output cleaning, private files,
cross-session locks, the JSON-RPC output stream and the account's paths.

HOME, CACHE, CONFIG, INSTALLED, OUT and READ_ONLY are rebound at run time (set_home, serve, serve-codex) and the
tests swap run_cmd, so other modules always read them as util.NAME: `from .util import HOME` would keep the value it
had at import.
"""
import contextlib
import fcntl
import json
import os
import pwd
import re
import shlex
import signal
import stat
import subprocess
import threading
import time

from .sites import ADMIN, ANSI, NAME_RE, UNTRUSTED

HOME = CACHE = CONFIG = INSTALLED = None  # set_home sets them before any mode runs
OUT = None  # serve points it at the real stdout
# serve-codex: only the tools that never ask exist. Codex has no way to force an ask, and a trusted repo's config can
# switch its approvals off, so the server itself refuses the rest.
READ_ONLY = False
LOCK = threading.Lock()
OUT_LOCK = threading.Lock()


class Refuse(Exception):
    """The call cannot go ahead; the message says what the member should do."""


class Cancelled(Exception):
    pass


class Call:
    def __init__(self, rid=None, token=None):
        self.rid, self.token, self.sent, self.procs, self.cancelled = rid, token, 0, set(), threading.Event()


def set_home(home):
    global HOME, CACHE, CONFIG, INSTALLED
    HOME = os.path.realpath(home)
    CACHE, CONFIG = HOME + "/.cache/uw3-hpc", HOME + "/.config/uw3-hpc/config.json"
    INSTALLED = HOME + "/.local/share/uw3-hpc/hpc_mcp.py"


def need(ok, msg):
    if not ok:
        raise Refuse(msg)


def q(s):
    return shlex.quote(str(s))


def is_name(s):
    return isinstance(s, str) and re.fullmatch(NAME_RE, s) is not None and ".." not in s


def untrusted(text, site=None):
    if site == "kaiju-agent":  # the agent account writes this text itself: only parsed fixed fields reach Claude
        return "\n(free text from the agent account is not shown; ssh kaiju-agent to look)"
    return "\n" + UNTRUSTED + "\n" + (text.strip("\n") or "(no output)")


def refusal(fn, *a, **kw):
    """The message fn refuses with, or "" if it goes through."""
    try:
        fn(*a, **kw)
    except (Refuse, Cancelled) as e:
        return str(e) or "cancelled"
    return ""


def clean(text, cap=None):
    """Printable ASCII and newlines only, at most cap chars (the first quarter, 2,000 by default, and the tail)."""
    cap, text = cap or ADMIN["out_chars"], re.sub(r"[^\n -~]", "?", ANSI.sub("", text).replace("\r\n", "\n")
                                                     .replace("\t", " "))
    head, mark = min(2000, cap // 4), "\n[... %d chars cut ...]\n" % (len(text) - cap)
    return text if len(text) <= cap else text[:head] + mark + text[-(cap - head - len(mark)):]


def read_json(path):
    with contextlib.suppress(OSError, ValueError), open(path) as f:
        return json.load(f)


def write_private(path, text, append=False):
    tmp = path if append else "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if append else os.O_TRUNC)
    with os.fdopen(os.open(tmp, flags, 0o600), "a" if append else "w") as f:
        f.write(text)
    if not append:
        os.replace(tmp, path)


def ensure_cache():
    for d in (CACHE, CACHE + "/tmp"):
        os.makedirs(d, mode=0o700, exist_ok=True)
        st = os.lstat(d)
        need(not stat.S_ISLNK(st.st_mode) and st.st_uid == os.getuid(), "%s must be a real directory you own" % d)
        os.chmod(d, 0o700)


@contextlib.contextmanager
def locked(name):
    """flock is shared by every Claude session's server and released by the kernel if one is killed."""
    with os.fdopen(os.open("%s/%s.mutex" % (CACHE, name), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)) as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def emit(msg):
    with OUT_LOCK:
        OUT.write((json.dumps(msg, separators=(",", ":")) + "\n").encode())
        OUT.flush()


def progress(ctx, msg):
    if ctx and ctx.token is not None and not ctx.cancelled.is_set():
        ctx.sent += 1
        emit({"jsonrpc": "2.0", "method": "notifications/progress",
              "params": {"progressToken": ctx.token, "progress": ctx.sent, "message": clean(msg, 300)}})


def child_env():
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": HOME, "USER": pwd.getpwuid(os.getuid()).pw_name,
           "LANG": "C", "LC_ALL": "C"}
    sock = os.environ.get("SSH_AUTH_SOCK", "")
    with contextlib.suppress(OSError):
        env.update({"SSH_AUTH_SOCK": sock} if sock and stat.S_ISSOCK(os.stat(sock).st_mode) else {})
    return env


def killgroup(p, sig=signal.SIGTERM):
    with contextlib.suppress(OSError):
        os.killpg(p.pid, sig)


def drain(f, buf):
    for chunk in iter(lambda: f.read(65536), b""):
        if sum(map(len, buf)) < 1 << 20:  # keep the first MB: a hostile remote must not exhaust memory
            buf.append(chunk)


def run_cmd(argv, data=None, timeout=None, ctx=None, tick=None, env=None):
    """Every child process starts here (the tests swap it for a recorder); returns (rc, stdout, stderr).
    No child shares our stdout (remote bytes could forge JSON-RPC); each gets its own group so cancel kills all."""
    ctx, bufs = ctx or Call(), ([], [])
    p = subprocess.Popen(argv, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env or child_env(), start_new_session=True)
    readers = [threading.Thread(target=drain, args=a, daemon=True) for a in zip((p.stdout, p.stderr), bufs)]
    with LOCK:
        ctx.procs.add(p)
    try:
        for t in readers:
            t.start()
        if data is not None:
            with contextlib.suppress(OSError):
                p.stdin.write(data.encode())
                p.stdin.close()
        t0 = last = time.time()
        while p.poll() is None:
            if ctx.cancelled.wait(0.2):
                raise Cancelled()
            need(not timeout or time.time() - t0 < timeout, "no answer in %s s; check the network (VPN?)" % timeout)
            if tick and time.time() - last >= 10:
                last = time.time()
                tick(last - t0)
    finally:
        for sig in (signal.SIGTERM, signal.SIGKILL) if p.poll() is None else ():
            killgroup(p, sig)
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(2)
        with LOCK:
            ctx.procs.discard(p)
    for t in readers:
        t.join(5)
    return (p.returncode,) + tuple(b"".join(b).decode("utf-8", "replace") for b in bufs)
