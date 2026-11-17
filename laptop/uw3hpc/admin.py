"""Terminal modes: install, doctor, reset and selftest, and the settings and registration install prints."""
import contextlib
import hashlib
import json
import os
import pwd
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile

from . import util
from .config import expand, load_config
from .sites import ADMIN, HUMAN, MARKER, RSYNC, SITES, SSH_ADD, SSH_KEYGEN
from .transport import key_test, lockfile
from .util import Refuse, child_env, clean, ensure_cache, need, read_json, refusal, write_private

SRC = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # the folder holding hpc_mcp.py
# Exactly what install copies and doctor expects, relative to SRC. The tests check it against the package folder,
# so a new module cannot be left out.
SHIPPED = tuple(["hpc_mcp.py", "managed-settings.json", "managed-settings-linux.json", "codex-requirements.toml"]
                + ["uw3hpc/%s.py" % m for m in (
    "__init__", "admin", "config", "files", "protocol", "scheduler", "sites", "tools", "transport", "util")]
    + ["uw3hpc/agent/%s.sh" % s for s in ("cancel", "start", "status")] + ["uw3hpc/hooks/notify.sh"])

# Conveniences only: what must hold whatever a project or the member sets is in managed-settings.json.
SETTINGS = {"permissions": {"allow": ["mcp__hpc__status", "mcp__hpc__wait", "mcp__hpc__get"],
                            "additionalDirectories": ["~/hpc/downloads", "~/hpc/uploads"]}}
TEMPLATE = {"downloads": "~/hpc/downloads", "uploads": "~/hpc/uploads", "sites": {s: dict(
    {"user": "CHANGEME-agent" if s == "kaiju-agent" else "CHANGEME", "key": "~/.ssh/id_ed25519_" + s.replace("-", "_")},
    **{"gadi": {"project": "CHANGEME", "base": "/scratch/PROJECT/USER/hpc", "storage": "scratch/PROJECT+gdata/PROJECT"},
       "setonix": {"project": "CHANGEME", "base": "/scratch/PROJECT/USER/hpc"},
       "kaiju": {"base": "/home/USER/hpc"}}.get(s, {}),
    **({"max_core_hours": ADMIN["core_hours"]} if s in HUMAN else {})) for s in SITES}}

# /usr/bin/python3 is Apple's xcrun shim, which runs whatever DEVELOPER_DIR names, and a project's settings env
# reaches MCP servers: env -i starts the real Python with nothing inherited (serve asks launchd for the ssh agent).
REGISTER = ["/usr/bin/env", "-i", "/usr/bin/python3", "-I", "INSTALLED", "serve"]
LINUX = sys.platform.startswith("linux")
# Root-owned, it outranks every user and project file: only it stops a trusted repo's hooks and MCP servers, which run
# outside the sandbox with the member's ssh agent. One file per OS, so a Linux-only key never makes Mac members sudo.
MANAGED = ("/etc/claude-code/managed-settings.json" if LINUX else
           "/Library/Application Support/ClaudeCode/managed-settings.json")
POLICY = "managed-settings-linux.json" if LINUX else "managed-settings.json"
ROOT_GROUP = "root" if LINUX else "wheel"  # Debian and Ubuntu have no wheel group
# A configuration profile for Claude Code's preferences domain outranks the file, which then counts for a few keys only.
PROFILES = () if LINUX else ("/Library/Managed Preferences/com.anthropic.claudecode.plist",
                             "/Library/Managed Preferences/USER/com.anthropic.claudecode.plist")
SYSROOT = ""  # --home sets it to the test home, so doctor never looks at the real /Library there
XCODE_SELECT, GIT = "/usr/bin/xcode-select", "/usr/bin/git"
# Codex: requirements.toml is the root-owned layer a member's or a trusted repo's config cannot loosen. The layers that
# outrank it and that a local check can see must be absent; a ChatGPT workspace's cloud requirements cannot be seen.
CODEX_REQ = "/etc/codex/requirements.toml"
CODEX_OVER = ("/etc/codex/managed_config.toml", "/Library/Managed Preferences/com.openai.codex.plist",
              "/Library/Managed Preferences/USER/com.openai.codex.plist")
CODEX_REGISTER = REGISTER[:-1] + ["serve-codex"]


def agent_ok(path, runtime):
    """A Linux agent socket serve may hand to ssh: under the member's runtime folder, which sandboxed commands cannot
    write, a socket of theirs, and every folder on the way theirs and closed to others."""
    if not (path and re.fullmatch(r"/[A-Za-z0-9._/-]+", path) and os.path.realpath(path) == path
            and path.startswith(runtime + "/")):
        return False
    with contextlib.suppress(OSError):
        st, d = os.lstat(path), os.path.dirname(path)
        ok = stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()
        while ok and len(d) >= len(runtime):
            st, d = os.lstat(d), os.path.dirname(d)
            ok = stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o022
        return ok
    return False


def agent_sock():
    """The ssh agent serve uses, as env -i leaves it none: launchd's on macOS; on Linux the systemd user manager's
    SSH_AUTH_SOCK, where gcr, gnome-keyring and OpenSSH's own user unit publish it."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        if not LINUX:
            return subprocess.run(["/bin/launchctl", "getenv", "SSH_AUTH_SOCK"], capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        run = "/run/user/%d" % os.getuid()
        out = subprocess.run(["/usr/bin/systemctl", "--user", "show-environment"], capture_output=True, text=True,
                             timeout=5, env={"XDG_RUNTIME_DIR": run, "DBUS_SESSION_BUS_ADDRESS": "unix:path=%s/bus"
                                             % run}).stdout
        sock = ([ln[14:] for ln in out.splitlines() if ln.startswith("SSH_AUTH_SOCK=")] or [""])[-1]
        return sock if agent_ok(sock, run) else ""
    return ""


def release(top):
    """The release hash: sha256 of the "sha256  path" lines of the shipped files, sorted by path. In that folder,
    find hpc_mcp.py managed-settings*.json codex-requirements.toml uw3hpc -type f | LC_ALL=C sort | xargs shasum -a 256
    | shasum -a 256 prints the same."""
    lines = []
    for rel in sorted(SHIPPED):
        with open(os.path.join(top, rel), "rb") as f:
            lines.append("%s  %s\n" % (hashlib.sha256(f.read()).hexdigest(), rel))
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def claude_version():
    """The terminal's claude as "2.1.316", "unknown" or "not found", and as a tuple to compare."""
    claude = shutil.which("claude")
    v = tuple(map(int, re.findall(r"[0-9]+", util.run_cmd([claude, "--version"], timeout=30, env=dict(os.environ))[1]
                                  if claude else "")[:3]))
    return ".".join(map(str, v)) or ("unknown" if claude else "not found"), v


def laptop_checks():
    """What install and doctor check first, as (ok, line, install refuses). macOS: /usr/bin/python3 and git are stubs
    until Apple's developer tools are installed, and rsync must be the one the tests ran: no guessing at older ones.
    Linux: the distribution's packages, and what the sandbox needs to start (doctor fails on those; install does
    not)."""
    fix = "sudo apt-get install %s" if LINUX else "xcode-select --install"
    rc, dev, _ = util.run_cmd([XCODE_SELECT, "-p"], timeout=30) if not LINUX else (0, "", "")
    tools = LINUX or rc == 0 and os.path.isdir(dev.strip())
    # The interpreter the registration names, started as it starts there; the stub would pop up an installer instead.
    rc, ver, _ = util.run_cmd(["/usr/bin/env", "-i", "/usr/bin/python3", "-I", "-c", "import sys; print("
                               "'%d.%d.%d' % sys.version_info[:3])"], timeout=60) if tools else (1, "", "")
    py = tuple(map(int, ver.split("."))) if rc == 0 and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\n?", ver) else ()
    rrc, out, err = util.run_cmd([RSYNC, "--version"], timeout=30)
    rsync = clean((out or err).strip().split("\n")[0], 80) or "no output"
    # GNU rsync: 3.2.5 has the 2022 path-checking fix; distributions backport later ones under 3.2.x numbers.
    gnu = tuple(map(int, (re.findall(r"^rsync +version ([0-9]+)\.([0-9]+)\.([0-9]+)", out) or [()])[0]))
    git = util.run_cmd([GIT, "--version"], timeout=30) if tools else (1, "", "")
    cs, cv = claude_version()
    checks = [] if LINUX else [(tools, "Apple's developer tools at %s (if not: xcode-select --install)" % (
        clean(dev.strip(), 200) or "?"), True)]
    checks += [(py >= (3, 9), "/usr/bin/python3 %s, want 3.9 or later (if not: %s)" % (
        ".".join(map(str, py)) or "does not run", fix % "python3" if LINUX else fix), True),
        (rrc == 0 and gnu >= (3, 2, 5), "%s is GNU rsync 3.2.5 or later; found \"%s\" (if not: %s)" % (
            RSYNC, rsync, fix % "rsync"), True) if LINUX else
        (rrc == 0 and out.startswith("openrsync"), "%s is openrsync, the only rsync tested; found \"%s\" (if not: "
                                                   "update to macOS 15 or later)" % (RSYNC, rsync), True),
        (git[0] == 0, "%s runs, for install's commit check (if not: %s)" % (GIT, fix % "git" if LINUX else fix), True),
        (cv >= ADMIN["claude_min"], "claude %s in the terminal, want %d.%d.%d or later (if not: claude update; VS "
                                    "Code's own copy is not checked)" % ((cs,) + ADMIN["claude_min"]), False)]
    if LINUX:
        userns = ""
        with contextlib.suppress(OSError), open("/proc/sys/kernel/apparmor_restrict_unprivileged_userns") as f:
            userns = f.read().strip()
        checks += [(all(os.access(p, os.X_OK) for p in ("/usr/bin/bwrap", "/usr/bin/socat")), "/usr/bin/bwrap and "
                    "/usr/bin/socat, which the sandbox needs (if not: %s)" % fix % "bubblewrap socat", False),
                   (userns != "1" or os.path.isfile("/etc/apparmor.d/bwrap"), "Ubuntu's AppArmor rule lets bubblewrap "
                    "make its namespaces (if not: add the profile in the README's Linux section)", False)]
    return checks


def git_status():
    """(rc, a line per shipped file in SRC that is not byte for byte in the last commit, git's error). ls-tree, not
    status: status runs the checkout's core.fsmonitor and clean filters, which .git/config can name."""
    rc, out, err = util.run_cmd([GIT, "-C", SRC, "ls-tree", "-r", "HEAD", "--"] + list(SHIPPED), timeout=30)
    if rc:
        return rc, out, err
    tree, bad = dict(line.split("\t", 1)[::-1] for line in out.splitlines() if "\t" in line), []
    for rel in SHIPPED:
        oid = ""
        with contextlib.suppress(OSError), open(os.path.join(SRC, rel), "rb") as f:
            blob = f.read()
            oid = hashlib.sha1(b"blob %d\0" % len(blob) + blob).hexdigest()  # git's id for the file as committed
        mode, kind, have = (tree.get(rel, "").split() + ["", "", ""])[:3]
        if not (oid and kind == "blob" and mode in ("100644", "100755") and have == oid):
            bad.append("%s %s\n" % ("differs" if rel in tree else "not committed", rel))
    return 0, "".join(bad), ""


def sudo_line():
    """The one line a member pastes: install makes no root files itself."""
    src = os.path.join(os.path.dirname(util.INSTALLED), POLICY)
    return "sudo install -d -o root -g %s -m 0755 %s && sudo install -o root -g %s -m 0644 %s %s" % (
        ROOT_GROUP, util.q(os.path.dirname(MANAGED)), ROOT_GROUP, util.q(src), util.q(MANAGED))


def managed_problems(path, want, root=0):
    """What doctor fails on, and serve refuses every call over, in the managed settings: anyone who can write the file,
    its folder or a drop-in can loosen it; Claude Code, running as the member, starts without a policy it cannot read;
    and a key beyond ours (a hook, a status line, another server) runs outside the sandbox with the ssh agent."""
    try:
        dst, st = os.lstat(os.path.dirname(path)), os.lstat(path)
    except OSError:
        return ["missing"]
    probs = [] if stat.S_ISDIR(dst.st_mode) and dst.st_uid == root else ["folder not a root-owned folder"]
    probs += ["folder writable by group or others"] if dst.st_mode & 0o022 else []
    # Claude Code merges every managed-settings.d/*.json but hidden ones over the file, later values winning.
    drop = os.path.join(os.path.dirname(path), "managed-settings.d")
    with contextlib.suppress(FileNotFoundError):
        dd = os.lstat(drop)
        probs += [] if stat.S_ISDIR(dd.st_mode) and dd.st_uid == root and not dd.st_mode & 0o022 else [
            "managed-settings.d is not a folder only root can write"]
        try:
            names = sorted(n for n in os.listdir(drop) if n.endswith(".json") and not n.startswith("."))
        except OSError:
            names = ["(unreadable)"]
        probs += ["managed-settings.d holds %s, which override this file (remove them, or ask whoever put them there)"
                  % ", ".join(names)] if names else []
    if not stat.S_ISREG(st.st_mode):
        return probs + ["not a plain file"]
    probs += [] if st.st_uid == root else ["not owned by root"]
    probs += ["writable by group or others"] if st.st_mode & 0o022 else []
    probs += [] if st.st_mode & 0o004 else ["not readable by everyone"]
    have = read_json(path)
    if not isinstance(have, dict):
        return probs + ["unreadable or not a JSON object"]
    if json.dumps(have, sort_keys=True) == json.dumps(want, sort_keys=True):  # exactly ours; true is not 1
        return probs
    miss = lacks(want, have)
    extra = [k for k in lacks(have, want) if k not in miss]
    return probs + (["lacks " + ", ".join(miss)] if miss else []) + (["adds " + ", ".join(extra)] if extra else []) + (
        [] if miss or extra else ["differs from ours"])


def managed_gate():
    """Why serve refuses every call, or "": without the root file nothing fences Claude's own commands beside hpc.
    Under --home (tests only) the file may be the account's own."""
    path, ours = SYSROOT + MANAGED, os.path.join(SRC, POLICY)
    policy = read_json(ours)
    probs = managed_problems(path, policy, os.getuid() if SYSROOT else 0) if isinstance(policy, dict) else [
        "cannot read " + ours]
    return "" if not probs else (
        "the managed settings file %s is not in place (%s), so hpc refuses every call: without it Claude's own "
        "commands are not fenced. In a terminal run `/usr/bin/python3 -I %s doctor` and paste the sudo line it "
        "prints." % (path, "; ".join(probs), util.INSTALLED))


def codex_requirements():
    """Ours with the member's home filled in: Codex matches the server's argv exactly and expands no variables."""
    with open(os.path.join(SRC, "codex-requirements.toml")) as f:
        return f.read().replace("@HOME@", util.HOME)


def codex_sudo_line():
    src = util.CACHE + "/codex-requirements.toml"  # doctor-codex writes it; the gate compares with ours, not with it
    return "sudo install -d -o root -g wheel -m 0755 %s && sudo install -o root -g wheel -m 0644 %s %s" % (
        util.q(os.path.dirname(CODEX_REQ)), util.q(src), util.q(CODEX_REQ))


def codex_problems(path, root=0):
    """What doctor-codex fails on, and serve-codex refuses every call over: as managed_problems, compared byte for byte
    (Python 3.9 has no TOML reader), plus any layer that outranks the file."""
    try:
        dst, st = os.lstat(os.path.dirname(path)), os.lstat(path)
    except OSError:
        return ["missing"]
    probs = [] if stat.S_ISDIR(dst.st_mode) and dst.st_uid == root else ["folder not a root-owned folder"]
    probs += ["folder writable by group or others"] if dst.st_mode & 0o022 else []
    if not stat.S_ISREG(st.st_mode):
        return probs + ["not a plain file"]
    probs += [] if st.st_uid == root else ["not owned by root"]
    probs += ["writable by group or others"] if st.st_mode & 0o022 else []
    probs += [] if st.st_mode & 0o004 else ["not readable by everyone"]
    have = None
    with contextlib.suppress(OSError, UnicodeDecodeError), open(path) as f:
        have = f.read()
    probs += [] if have == codex_requirements() else ["differs from ours"]
    over = [SYSROOT + p.replace("USER", pwd.getpwuid(os.getuid()).pw_name) for p in CODEX_OVER]
    return probs + ["outranked by %s (ask whoever put it there)" % p for p in over if os.path.lexists(p)]


def codex_gate():
    """Why serve-codex refuses every call, or "": without the root file nothing fences Codex's own commands."""
    path = SYSROOT + CODEX_REQ
    probs = codex_problems(path, os.getuid() if SYSROOT else 0)
    return "" if not probs else (
        "the Codex requirements file %s is not in place (%s), so hpc refuses every call: without it Codex's own "
        "commands are not fenced. In a terminal run `/usr/bin/python3 -I %s doctor-codex` and paste the sudo line it "
        "prints." % (path, "; ".join(probs), util.INSTALLED))


def install_problems(top, uid):
    """What doctor fails on in an installed copy: anything install did not put there, a shipped file missing,
    a link, or anything writable or owned by another account."""
    if not os.path.isdir(top) or os.path.islink(top):
        return ["not installed"]
    want, dirs = set(SHIPPED), {os.path.dirname(p) for p in SHIPPED}
    probs = []
    for d, subdirs, files in os.walk(top):
        for n in sorted(subdirs + files):
            rel, st = os.path.relpath(os.path.join(d, n), top), os.lstat(os.path.join(d, n))
            if not (rel in want and stat.S_ISREG(st.st_mode) or rel in dirs and stat.S_ISDIR(st.st_mode)):
                probs.append("extra " + rel)
                if n in subdirs:
                    subdirs.remove(n)
                continue
            probs += ["writable " + rel] if st.st_mode & 0o222 else []
            probs += ["not yours " + rel] if st.st_uid != uid else []
    st = os.lstat(top)
    probs += ["writable folder"] if st.st_mode & 0o222 else []
    probs += ["folder not yours"] if st.st_uid != uid else []
    return probs + ["missing " + p for p in SHIPPED if not os.path.isfile(os.path.join(top, p))
                    or os.path.islink(os.path.join(top, p))]


def unlock(top):
    """Make an installed copy deletable again: install leaves its folders read-only."""
    for d, _, _ in os.walk(top):
        with contextlib.suppress(OSError):
            os.chmod(d, 0o700)


def install():
    d = os.path.dirname(util.INSTALLED)
    checks = laptop_checks()
    for ok, line, refuse in checks:
        if not ok:
            print("%s %s" % ("FAIL" if refuse else "WARN", line))
    if not all(ok for ok, _, refuse in checks if refuse):
        return print("Nothing installed: fix each FAIL above first.") or 1
    # Claude can edit this checkout without asking (acceptEdits), so only what the last commit holds is installed.
    rc, out, err = git_status()
    if rc:
        return print("git cannot read the last commit of %s, so nothing is installed: install from a git clone of the "
                     "repository (%s)" % (SRC, clean(err or out, 300).strip())) or 1
    if out.strip():
        return print("%s differs from the last commit: review it (git diff), commit, then install\n%s"
                     % (SRC, clean(out, 2000))) or 1
    for rel in SHIPPED:
        with contextlib.suppress(OSError):
            if stat.S_ISREG(os.lstat(os.path.join(SRC, rel)).st_mode):
                continue
        return print("%s is missing or not a plain file" % os.path.join(SRC, rel)) or 1
    os.makedirs(os.path.dirname(d), exist_ok=True)
    os.makedirs(os.path.dirname(util.CONFIG), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(util.CONFIG), 0o700)
    for root in ("downloads", "uploads"):
        os.makedirs("%s/hpc/%s" % (util.HOME, root), exist_ok=True)
        open("%s/hpc/%s/%s" % (util.HOME, root, MARKER), "a").close()
    # The new copy is built beside the old one; the old one is renamed, not moved into a folder, as macOS refuses to
    # move a read-only folder into another one.
    new = tempfile.mkdtemp(prefix=".uw3-hpc-new-", dir=os.path.dirname(d))
    old = os.path.join(os.path.dirname(d), ".uw3-hpc-old-%d-%s" % (os.getpid(), secrets.token_hex(4)))
    try:
        for rel in SHIPPED:
            os.makedirs(os.path.dirname(os.path.join(new, rel)), exist_ok=True)
            with open(os.path.join(SRC, rel), "rb") as src, open(os.path.join(new, rel), "xb") as f:
                f.write(src.read())
            os.chmod(os.path.join(new, rel), 0o444)
        for p, _, _ in os.walk(new, topdown=False):
            os.chmod(p, 0o555)
        # Two renames, not an atomic swap: a server starting between them fails; running ones have their code loaded.
        if os.path.lexists(d):
            os.rename(d, old)
        try:
            os.rename(new, d)
        except OSError:
            with contextlib.suppress(OSError):
                os.rename(old, d)
            raise
    finally:
        for p in (new, old):
            if os.path.islink(p):
                os.unlink(p)
            elif os.path.isdir(p):
                unlock(p)
                shutil.rmtree(p, ignore_errors=True)
    ensure_cache()
    with contextlib.suppress(FileExistsError), os.fdopen(os.open(util.CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                                                 0o600), "w") as f:
        f.write(json.dumps(TEMPLATE, indent=2) + "\n")
    # Numbered as the README's set-up steps, and the managed file before the registration: hpc refuses calls until
    # the file is in place.
    print("Installed %s, its uw3hpc package and the policy files (release sha256 %s; doctor prints it too)\n\n"
          "Next, as in the README's set-up:\n3. Edit %s: delete the sites you do not use; replace every CHANGEME, "
          "PROJECT and USER in user, key, project, base and storage.\n4. Install the managed settings with your "
          "password, once per computer and again whenever doctor fails them. Afterwards hpc is Claude's only MCP "
          "server and no hooks run (the README says what else changes), and hpc refuses every call without it; undo "
          "with sudo rm %s\n   %s\n5. Merge this into ~/.claude/settings.json:\n%s\n6. Register it for every project "
          "(first `claude mcp remove --scope user hpc` if it exists), then check:\n   claude mcp add --scope user hpc "
          "-- %s\n   /usr/bin/python3 -I %s doctor\nEach day, load each key: ssh-add -t 12h KEY" % (
              util.INSTALLED, release(d), util.CONFIG, util.q(MANAGED), sudo_line(), json.dumps(SETTINGS, indent=2),
              " ".join(REGISTER).replace("INSTALLED", util.INSTALLED), util.INSTALLED))
    print("\nCodex instead of Claude Code: skip 4 to 6 and follow the README's Codex section (doctor-codex).")
    return 0


def lacks(want, have, path=""):
    """The entries of want missing from have: lists must be covered, other values equal (true is not 1)."""
    if isinstance(want, dict):
        return [m for k, v in want.items() if k != "additionalDirectories" for m in lacks(
            v, have.get(k) if isinstance(have, dict) else None, path + "." + k)]
    ok = all(x in have for x in want) if isinstance(want, list) and isinstance(have, list) else (
        want == have and type(want) is type(have))
    return [] if ok else [path[1:]]


def doctor(cfgpath, codex=False):
    """codex: the checks for serve-codex, Codex's registration and its requirements file instead of Claude Code's."""
    fails, cfg = [], {"sites": {}}

    def say(ok, msg, bad="FAIL"):
        print("%-4s %s" % ("PASS" if ok else bad, msg))
        fails.extend([] if ok or bad != "FAIL" else [msg])

    for ok, line, _ in laptop_checks():
        if codex and line.startswith("claude "):
            cx = shutil.which("codex")
            say(bool(cx), "codex in the terminal: %s" % (clean(cx, 200) if cx else "not found"), "WARN")
            continue
        say(ok, line)
    if SRC != os.path.dirname(util.INSTALLED):  # run from a checkout: would install take it?
        rc, out, _ = git_status()
        say(rc == 0 and not out.strip(), "checkout %s matches its last commit, so install takes it (if not: review and "
            "commit, or clone the repository)" % SRC, "WARN")
    if codex:
        want, toml = [x.replace("INSTALLED", util.INSTALLED) for x in CODEX_REGISTER], ""
        with contextlib.suppress(OSError, UnicodeDecodeError), open(util.HOME + "/.codex/config.toml") as f:
            toml = f.read()
        # No TOML reader in 3.9, so a text check; the requirements file is what pins the exact command.
        say("[mcp_servers.hpc]" in toml and "".join(json.dumps(want[1:]).split()) in "".join(toml.split()),
            "~/.codex/config.toml registers hpc as: command = \"/usr/bin/env\", args = %s" % json.dumps(want[1:]),
            "WARN")
    else:
        reg, want = ((read_json(util.HOME + "/.claude.json") or {}).get("mcpServers") or {}).get("hpc") or {}, [
            x.replace("INSTALLED", util.INSTALLED) for x in REGISTER]
        say([reg.get("command")] + (reg.get("args") or []) == want and not reg.get("env"), "registered at user scope "
            "exactly as: claude mcp add --scope user hpc -- " + " ".join(want))
    top = os.path.dirname(util.INSTALLED)
    probs = install_problems(top, os.getuid())
    say(not probs, "installed copy %s: " % top + ("; ".join(probs[:10]) + " (rerun install)" if probs else
                                                  "the %d shipped files, read-only and yours; release sha256 %s"
                                                  % (len(SHIPPED), release(top))))
    if codex:
        ensure_cache()
        write_private(util.CACHE + "/codex-requirements.toml", codex_requirements())
        path = SYSROOT + CODEX_REQ
        probs = codex_problems(path)
        say(not probs, "Codex requirements %s: " % path + ("; ".join(probs) + ". Fix: " + codex_sudo_line() if probs
                                                          else "root's, readable by all, exactly ours"))
    else:
        ours, path = os.path.join(SRC, POLICY), SYSROOT + MANAGED
        policy = read_json(ours)
        probs = managed_problems(path, policy) if isinstance(policy, dict) else ["cannot read " + ours]
        say(not probs, "managed settings %s: " % path + ("; ".join(probs) + ". Fix: " + sudo_line() if probs else
                                                         "root's, readable by all, exactly " + ours))
        prof = [SYSROOT + p.replace("USER", pwd.getpwuid(os.getuid()).pw_name) for p in PROFILES]
        prof = [p for p in prof if os.path.lexists(p)]
        if PROFILES:
            say(not prof, "no Claude Code configuration profile outranks that file%s" % (
                ": " + ", ".join(prof) if prof else ""), "WARN")
        say(os.environ.get("HOME") == util.HOME, "$HOME is %s, as the managed allowlist names hpc by ${HOME}/.local/"
            "share/uw3-hpc/hpc_mcp.py" % util.HOME, "WARN")
    sock = agent_sock()
    say(os.environ.get("SSH_AUTH_SOCK") == sock, "this terminal's ssh agent is the login agent the server uses (%s)%s"
        % (sock or "none found", " (if not: use your desktop's agent, or run systemctl --user import-environment "
           "SSH_AUTH_SOCK where ssh-add -l lists your keys; it must be under /run/user)" if LINUX else ""), "WARN")
    err = refusal(lambda: cfg.update(load_config(cfgpath)))
    say(not err, err or "config " + cfgpath)
    no_agent = dict(child_env(), SSH_AUTH_SOCK="/nonexistent")  # so ssh-keygen tests the file, not the agent
    for site, s in cfg["sites"].items():
        k = s["key"]
        have = os.path.isfile(k) and os.path.isfile(k + ".pub")
        bare = have and util.run_cmd([SSH_KEYGEN, "-y", "-P", "", "-f", k], timeout=15, env=no_agent)[0] == 0
        unknown = [h for h in sorted({SITES[site]["login"], SITES[site]["copy"]})
                   if util.run_cmd([SSH_KEYGEN, "-F", h, "-f", util.HOME + "/.ssh/known_hosts"], timeout=15)[0]]
        say(have, "%s: key %s and %s.pub exist" % (site, k, k))
        say(have and not bare, "%s: key has a passphrase (if not: ssh-keygen -p -f %s)" % (site, k))
        say(have and util.run_cmd([SSH_ADD, "-T", k + ".pub"], timeout=15)[0] == 0, "%s: key is loaded (if not: "
            "ssh-add -t 12h %s)" % (site, k), "WARN")
        say(not unknown, "%s: hosts in known_hosts (if not: ssh once to %s)" % (site, " ".join(unknown)), "WARN")
    if codex:
        return 1 if fails else 0
    st = read_json(util.HOME + "/.claude/settings.json") or {}
    miss, net = lacks(SETTINGS, st), (st.get("sandbox") or {}).get("network") or {}
    say(not miss, "~/.claude/settings.json: " + (", ".join(miss) + " missing or different" if miss else "has every "
                                                  "setting install printed"))
    dirs = {os.path.realpath(expand(x)) for x in (st.get("permissions") or {}).get("additionalDirectories") or []}
    roots = {os.path.realpath(s[k]) for s in cfg["sites"].values() for k in ("downloads", "uploads")}
    say(roots <= dirs, "permissions.additionalDirectories has your download and upload folders " + " ".join(
        sorted(roots - dirs)))
    agents = [os.path.realpath(x) for x in (sock, os.environ.get("SSH_AUTH_SOCK")) if x]
    say(net.get("allowAllUnixSockets") is not True and not [p for p in net.get("allowUnixSockets") or [] if "launchd"
        in p or any(a.startswith(os.path.realpath(expand(p))) for a in agents)], "no sandbox.network Unix-socket "
        "setting lets sandboxed commands reach the ssh agent")
    return 1 if fails else 0


def reset_prompt(site, why):
    try:
        s = load_config(util.CONFIG)["sites"].get(site, {})
    except Refuse:  # a broken config must not stop the reset
        s = {}
    return ("%s locked: %s%s, so check the key first, in this terminal; it must log in without asking for a "
            "password:\n  %s\nType yes to clear: " % (site, why, SITES[site]["lockout"], key_test(site, s)))


def reset(site):
    if not os.path.lexists(lockfile(site)):
        return print("%s is not locked" % site) or 0
    try:
        # Separate read and write handles: "r+" needs a seekable file and a tty is not one.
        with open("/dev/tty") as tty, open("/dev/tty", "w") as out, open(lockfile(site)) as f:
            out.write(reset_prompt(site, clean(f.read(), 300)))
            out.flush()
            need(tty.readline().strip() == "yes", "left locked")
    except (OSError, Refuse) as e:
        return print(e if isinstance(e, Refuse) else "reset asks on a terminal: run it yourself in one") or 1
    os.unlink(lockfile(site))
    return print("%s unlocked" % site) or 0


def selftest():
    # The tests live beside the package in the repository; the installed copy has none.
    test = os.path.join(SRC, "tests", "test_unit.py")
    if not os.path.isfile(test):
        return print("no %s: run selftest in the repository checkout" % test) or 2
    return subprocess.call([sys.executable, "-I", test, SRC])
