"""The laptop side of get and put: checking, scrubbing and placing a download; snapshotting an upload."""
import contextlib
import os
import shutil
import stat
import tempfile

from . import util
from .sites import ADMIN, BLOCKED, SCRIPTS
from .util import Refuse, is_name, need


def lsize(p):
    with contextlib.suppress(FileNotFoundError):  # rsync renames its temp files while progress walks the tree
        return os.lstat(p).st_size
    return 0


def tree(top):
    return sorted((os.path.relpath(os.path.join(d, n), top), lsize(os.path.join(d, n)))
                  for d, _, files in os.walk(top) for n in files)


def capped(top, what):
    total = sum(n for _, n in tree(top))
    need(total <= ADMIN["get_call_mb"] << 20, "%s is over %d MB: get a smaller subpath" % (what, ADMIN["get_call_mb"]))
    return total


def scrub(top):
    """Drop what rsync should not have delivered: odd names, links, special or huge files, Claude instructions."""
    removed = 0
    for d, dirs, files in os.walk(top):
        for n in list(dirs) + files:
            p, st = os.path.join(d, n), os.lstat(os.path.join(d, n))
            kind_ok = stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode) and st.st_size <= ADMIN["get_file_mb"] << 20
            if not (is_name(n) and not BLOCKED.fullmatch(n) and kind_ok):
                removed += sum(len(f) for _, _, f in os.walk(p)) or 1  # a dropped folder counts its files
                shutil.rmtree(p) if stat.S_ISDIR(st.st_mode) else os.unlink(p)
                if n in dirs:
                    dirs.remove(n)
    return removed


def place(tmp, root, site, run):
    # Claude can write in root, so a link planted mid-way must not redirect cluster files: every step goes through
    # folder fds that never follow a link, and there is no copy fallback that would merge into a folder.
    flags, fds = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, []
    try:
        fds.append(os.open(root, flags))
        with contextlib.suppress(FileExistsError):
            os.mkdir(site, dir_fd=fds[0])
        fds.append(os.open(site, flags, dir_fd=fds[0]))
        for name in [run] + ["%s.%d" % (run, n) for n in range(2, 1000)]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(name, dir_fd=fds[1])  # atomic claim, so two sessions never merge into one folder
                os.rename(tmp, name, dst_dir_fd=fds[1])
                return os.path.join(root, site, name)
    except OSError as e:
        raise Refuse("could not place the download in %s/%s (%s); nothing was kept" % (root, site, e.strerror))
    finally:
        list(map(os.close, fds))
    raise Refuse("too many copies of %s in %s/%s: clean up old ones" % (run, root, site))


def mktmp():
    # Named by pid, so the next server can remove what a killed one left (shutdown has no time to clean up).
    return tempfile.mkdtemp(prefix="%d-" % os.getpid(), dir=util.CACHE + "/tmp")


def snapshot(src, dst):
    """Copy the upload into a private folder through fds that never follow a link, checking each file, and send the
    copy: Claude can write in uploads, so a checked folder could become a link to ~/.ssh before rsync reads it."""
    n = total = 0
    try:
        top = os.open(src, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise Refuse("nothing to upload: put the files in %s (a plain folder, not a link) first" % src)
    try:  # fwalk never descends through a link; each file is checked and read through one fd
        for d, dirs, files, dfd in os.fwalk(".", dir_fd=top):
            os.makedirs(os.path.join(dst, d), exist_ok=True)
            os.chmod(os.path.join(dst, d), os.fstat(dfd).st_mode & 0o755 | 0o700)  # a read-only source folder too
            for name in dirs + files:
                p, st = os.path.normpath(os.path.join(src, d, name)), os.stat(name, dir_fd=dfd, follow_symlinks=False)
                need(stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode), "%s is a link or special file" % p)
                if name in dirs:
                    continue
                with os.fdopen(os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd), "rb") as f:
                    st = os.fstat(f.fileno())
                    # A hard link can carry in a file the sandbox hides from Claude, such as a key.
                    need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "%s has other hard links: copy it" % p)
                    data = f.read((ADMIN["put_mb"] << 20) + 1 - total)
                n, total = n + 1, total + len(data)
                need(n <= ADMIN["put_files"] and total <= ADMIN["put_mb"] << 20, "the upload is over the cap of %d "
                     "files and %d MB" % (ADMIN["put_files"], ADMIN["put_mb"]))
                need(not ((data[:2] == b"#!" or name.endswith(SCRIPTS)) and b"\r" in data),
                     "%s has Windows line endings, which break job scripts: dos2unix it" % p)
                with open(os.path.join(dst, d, name), "wb") as out:
                    out.write(data)
                os.chmod(out.name, st.st_mode & 0o755)
    finally:
        os.close(top)
    return n, total
