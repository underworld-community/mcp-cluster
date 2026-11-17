"""Shared by the offline tests: which copy of the server to import, temp folders, and a guard so that no test
process starts ssh, scp or sftp, or rsync over the real ssh.

Every test takes the folder holding hpc_mcp.py as its first argument (default: the checkout above tests/), so the
same tests can run against another copy. Work folders are temporary and removed at exit, unless UW3HPC_TEST_DIR
names a folder to keep them in.
"""
import atexit
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

PY = "/usr/bin/python3"
HERE = os.path.dirname(os.path.realpath(__file__))

_Popen = subprocess.Popen


class GuardPopen(_Popen):
    def __init__(self, args, *a, **kw):
        words = [str(x) for x in (args if isinstance(args, (list, tuple)) else [args])]
        name = os.path.basename(words[0])
        if name in ("ssh", "scp", "sftp") or name == "rsync" and any("/usr/bin/ssh" in w for w in words):
            raise RuntimeError("test guard refused to start %r" % words[:2])
        super().__init__(args, *a, **kw)


subprocess.Popen = GuardPopen


def use(path=None):
    """Put the folder holding hpc_mcp.py (or hpc_mcp.py itself) on sys.path and return it; uw3hpc must come from it."""
    root = os.path.realpath(path or os.path.dirname(HERE))
    root = os.path.dirname(root) if os.path.isfile(root) else root
    sys.dont_write_bytecode = True  # keep the checkout and any installed copy free of __pycache__
    sys.path.append(root)
    import uw3hpc
    got = os.path.dirname(os.path.dirname(os.path.realpath(uw3hpc.__file__)))
    if got != root:
        raise SystemExit("uw3hpc came from %s, not %s" % (got, root))
    return root


def entry(root):
    """hpc_mcp.py as a module, for main()."""
    spec = importlib.util.spec_from_file_location("hpc_mcp_entry", os.path.join(root, "hpc_mcp.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rmtree(top):
    """shutil.rmtree that also gets through the read-only folders install makes."""
    for d, _, _ in os.walk(top):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    shutil.rmtree(top, ignore_errors=True)


def workdir(name):
    keep = os.environ.get("UW3HPC_TEST_DIR")
    if keep:
        d = os.path.join(os.path.realpath(keep), name)
        rmtree(d)
        os.makedirs(d)
        return d
    d = os.path.realpath(tempfile.mkdtemp(prefix="uw3hpc-%s-" % name))
    atexit.register(rmtree, d)
    return d


def copy_tree(root, dst, rels):
    """Copy the given files of a checkout into dst, as a checkout would hold them."""
    for rel in rels:
        os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
        shutil.copy(os.path.join(root, rel), os.path.join(dst, rel))


def managed_copy(root, home):
    """The managed settings file serve wants, under a --home, where it accepts the account's own copy: the root-owned
    one in /Library cannot be faked. Returns its folder."""
    from uw3hpc import admin
    d = os.path.realpath(home) + os.path.dirname(admin.MANAGED)
    os.makedirs(d, exist_ok=True)
    os.chmod(d, 0o755)
    shutil.copy(os.path.join(root, "managed-settings.json"), d)
    os.chmod(os.path.join(d, "managed-settings.json"), 0o644)
    return d


def codex_copy(root, home):
    """serve-codex's requirements file under a --home, rendered for that home. Returns its path."""
    from uw3hpc import admin
    h = os.path.realpath(home)
    os.makedirs(h + os.path.dirname(admin.CODEX_REQ), exist_ok=True)
    os.chmod(h + os.path.dirname(admin.CODEX_REQ), 0o755)
    with open(os.path.join(root, "codex-requirements.toml")) as f, open(h + admin.CODEX_REQ, "w") as out:
        out.write(f.read().replace("@HOME@", h))
    os.chmod(h + admin.CODEX_REQ, 0o644)
    return h + admin.CODEX_REQ


def git_copy(root, dst, rels):
    """copy_tree into a new git repository of its own and commit it all, as install wants a clean clone. git reads none
    of the account's config, so no hook, signing or template runs."""
    copy_tree(root, dst, rels)
    env = {"PATH": "/usr/bin:/bin", "HOME": dst, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@invalid", "GIT_COMMITTER_NAME": "test",
           "GIT_COMMITTER_EMAIL": "test@invalid"}
    for argv in (["init", "-q", "--template="], ["add", "-A"], ["commit", "-q", "--no-verify", "-m", "test copy"]):
        subprocess.run(["/usr/bin/git", "-C", dst] + argv, check=True, capture_output=True, env=env)


def submit_out(remote, ids):
    """What a submit login prints for the ssh command string remote: each job's marker, then its id from ids, as
    long as ids last; a job without an id is the one that failed, so nothing follows it. ids are output lines."""
    marks = re.findall(r"== uw3hpc [0-9a-f]{8} (?:[0-9]+|end)", remote)
    out = []
    for n, m in enumerate(marks):
        out.append(m)
        if m.endswith(" end") or n >= len(ids):
            break
        out.append(ids[n])
    return "".join(x + "\n" for x in out)
