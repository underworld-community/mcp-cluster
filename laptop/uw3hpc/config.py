"""The member's config file, and the download and upload roots it names."""
import json
import os
import re
import stat

from . import util
from .sites import ADMIN, HUMAN, MARKER, RPATH, SITES, USER
from .util import Refuse, is_name, need


def expand(p):
    return util.HOME + p[1:] if p == "~" or p.startswith("~/") else p


def load_config(path):
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as f:
            st = os.fstat(f.fileno())
            need(st.st_uid == os.getuid() and stat.S_ISREG(st.st_mode) and not st.st_mode & 0o022,
                 "%s must be a plain file you own and only you can write: chmod 600 %s" % (path, path))
            raw = json.load(f)
    except FileNotFoundError:
        raise Refuse("no config at %s: run `hpc_mcp.py install`, then fill in your sites" % path)
    except (OSError, ValueError) as e:
        raise Refuse("%s is a symlink, unreadable or not JSON: %s" % (path, e))
    need(isinstance(raw, dict), "%s must hold a JSON object" % path)
    cfg = {"sites": {}}
    for site, s in (raw.get("sites") or {}).items():
        s = s if isinstance(s, dict) else {}
        user, key, base, storage = (str(s.get(k, "")) for k in ("user", "key", "base", "storage"))
        key, base = expand(key), base.rstrip("/")
        for ok, why in (
                (site in SITES, "unknown site; known: " + ", ".join(SITES)),
                (not re.search("CHANGEME|PROJECT|USER", json.dumps(s)), "replace the CHANGEME, PROJECT and USER "
                 "placeholders, or delete the site"),
                (USER.fullmatch(user), "set user to your login name"),
                (not user.endswith("-adm"), "admin (-adm) accounts are never driven by Claude"),
                ((site == "kaiju-agent") == user.endswith("-agent"), "only kaiju-agent uses your -agent account"),
                (key.startswith("/") and not re.search(r"[\s'\"\\]", key), "key must be a path like ~/.ssh/id_x"),
                (site not in HUMAN or RPATH.fullmatch(base) and ".." not in base, "base must be an absolute folder"),
                (site not in ("gadi", "setonix") or is_name(s.get("project")), "set project (the allocation)"),
                (re.fullmatch(r"[a-z0-9/+]{0,200}", storage), "storage looks like scratch/m18+gdata/m18"),
                (type(s.get("max_core_hours", 1)) is int and s.get("max_core_hours", 1) >= 1,
                 "max_core_hours must be a whole number above 0")):
            need(ok, "in %s, site %s: %s" % (path, site, why))
        cfg["sites"][site] = {
            "user": user, "key": key, "base": base, "project": s.get("project"), "storage": storage,
            "max_core_hours": s.get("max_core_hours", ADMIN["core_hours"]),
            "downloads": expand(str(s.get("downloads", raw.get("downloads", "~/hpc/downloads")))),
            "uploads": expand(str(s.get("uploads", raw.get("uploads", "~/hpc/uploads"))))}
    return cfg


def check_root(path):
    """A download/upload root must be a marked folder away from credentials, settings and git repos."""
    real = d = os.path.realpath(path)
    low, home = real.lower(), util.HOME.lower()  # APFS ignores case and realpath keeps it: ~/.SSH is ~/.ssh
    need(low != home and not any(low == home + "/" + x or low.startswith(home + "/" + x + "/")
                                 for x in (".ssh", ".claude", "library", ".config", ".local", ".cache")),
         "%s is not allowed as a download/upload folder; use e.g. ~/hpc/downloads" % path)
    while d != os.path.dirname(d):
        need(not os.path.lexists(os.path.join(d, ".git")), "%s is inside the git repository %s" % (path, d))
        d = os.path.dirname(d)
    need(os.path.isfile(os.path.join(real, MARKER)), "%s has no %s marker: in a terminal, mkdir -p it and touch "
         "%s/%s" % (path, MARKER, path, MARKER))
    return real
