"""Scheduler queries: one cached listing per site per floor, shared by every session, and parsing what comes back."""
import json
import re
import time

from . import util
from .sites import ADMIN, AGENT_LINE, AGENT_STATUS, JOB, QFAIL, SACCT_MARK, SITES
from .transport import remote_text
from .util import clean, locked, need, q, read_json, untrusted, write_private

SUBMITS = {}  # filled by submit and task in tools, keyed by job_key
# qstat without -t lists only an array's parent; B is a parent with at least one element started.
GADI_STATES = {"B": "B (array begun: at least one element has started)"}
# squeue and sacct cut every sized field to its size: the id stays unsized so a pending range such as
# 1234_[5-1000%4] can be counted. Parsed fields come before the job name and reason, which can hold spaces.
SQUEUE = "%i %.9P %.8T %.10M %.30j %R"
SACCT = "JobID%30,State,ExitCode,Elapsed,JobName%30"


def cached(site, fetch):
    """One scheduler query per floor per site across every Claude session; returns (text, age)."""
    path = "%s/%s.json" % (util.CACHE, site)
    with locked(site):
        c = read_json(path)
        if c and 0 <= time.time() - c["t"] < SITES[site]["floor"]:
            return c["out"], time.time() - c["t"]
        out = fetch()
        write_private(path, json.dumps({"t": time.time(), "out": out}))
        return out, 0


def job_key(jid):
    """1234[].gadi-pbs, 1234[] and 1234 are one Gadi job: PBS numbers array and plain jobs from one sequence."""
    return jid.split(".")[0].replace("[]", "")


def ranges(tok):
    """The (first, last, step) index ranges of a Slurm array id such as 1234_7 or 1234_[4-10,12%2]; None if it is
    unreadable, e.g. a long pending range that squeue cut short (SLURM_BITSTR_LEN)."""
    m = re.fullmatch(r"[0-9]+_(?:([0-9]{1,9})|\[([0-9,:-]+)(?:%[0-9]+)?\])", tok)
    if not m:
        return None
    found = []
    for part in (m.group(1) or m.group(2)).split(","):
        r = re.fullmatch(r"([0-9]{1,9})(?:-([0-9]{1,9})(?::([1-9][0-9]{0,8}))?)?", part)
        if not r or int(r.group(2) or r.group(1)) < int(r.group(1)):
            return None
        found.append((int(r.group(1)), int(r.group(2) or r.group(1)), int(r.group(3) or 1)))
    return found


def same_job(site, t, jid):
    """Whether the listing id t is jid: 1234 stands for every element of its array, 1234_7 for that one element."""
    if site == "gadi":
        return job_key(t) == job_key(jid)
    base, _, idx = jid.partition("_")
    if t == jid or not idx and t.startswith(base + "_"):
        return True
    if not idx or not t.startswith(base + "_"):
        return False
    rs = ranges(t)
    if rs is None:  # a pending range cut short may hold the element
        return t.startswith(base + "_[")
    return any(a <= int(idx) <= b and (int(idx) - a) % s == 0 for a, b, s in rs)


def job_lines(site, out, jid, queue_only=False):
    return [x for x in (out.split(SACCT_MARK)[0] if queue_only else out).splitlines()
            if same_job(site, (x.split() or [""])[0], jid)]


def is_array(site, jid, lines):
    ids = [(x.split() or [""])[0] for x in lines]
    return "[]" in jid or any("[]" in t if site == "gadi" else "_" not in jid and t != jid for t in ids)


def line_state(site, line):
    # Slurm: a bounded split, so a job name or reason with spaces cannot move the state.
    tok = line.split() if site == "gadi" else line.split(None, 4)
    st = (tok[-2] if site == "gadi" else tok[2]) if len(tok) > 3 else None
    return None if st in (None, "F", "X") else st if re.fullmatch("[A-Z_]{1,20}", st) else "?"


def job_state(site, lines, jid):
    """None once nothing of jid is queued or running; for a Slurm array, how many elements are left in each state."""
    live = [(x.split()[0], s) for x in lines for s in [line_state(site, x)] if s]
    if site == "gadi" or "_" in jid or all(t == jid for t, _ in live):
        return (GADI_STATES.get(live[0][1], live[0][1]) if site == "gadi" else live[0][1]) if live else None
    n, cut = {}, set()
    for t, s in live:
        rs = [(0, 0, 1)] if t == jid else ranges(t)
        n[s] = n.get(s, 0) + (sum((b - a) // c + 1 for a, b, c in rs) if rs else 1)
        cut |= set() if rs else {s}
    total = sum(n.values())
    return "an array with %d%s element%s queued or running (%s)" % (
        total, "+" if cut else "", "s" if total > 1 or cut else "",
        ", ".join("%s %d%s" % (s, k, "+" if s in cut else "") for s, k in sorted(n.items())))


def parse_agent(out, jid=None):
    """Strict fixed-field parse; any other line (agent-controlled text) is dropped."""
    found = [[m.groups() for m in map(AGENT_LINE[k].fullmatch, out.splitlines()) if m] for k in ("task", "job")]
    return [t for t in found[0][-50:] if jid in (None, t[0])], found[1][:ADMIN["files_listed"]]


def agent_lines(tasks, jobs):
    lines = []
    for tid, st, rc, start, end, session, project, n, size in tasks:
        el = (int(end) if end != "-" else int(time.time())) - int(start) if start != "-" else "-"
        lines.append("task %s project=%s state=%s rc=%s started=%s ended=%s elapsed=%ss session=%s outbox=%s files, "
                     "%.1f MB" % (tid, project, st, rc, start, end, el, session, n, int(size) / 1e6))
    return lines + ["job %s %s elapsed=%s" % j for j in jobs]


def check_id(site, jid):
    need(jid is None or JOB[SITES[site]["sched"]].fullmatch(jid), "%r is not a %s %s id" % (
        jid, site, "task" if site == "kaiju-agent" else "job"))


def listing(cfg, site, ctx):
    """(text, age) of the site's shared listing, refused if the query failed."""
    u = q(cfg["sites"][site]["user"])
    cmd = {"gadi": "qstat -x -w -u " + u, "kaiju-agent": AGENT_STATUS}.get(
        site, "squeue -u %s -o %s" % (u, q(SQUEUE)))
    cmd += "" if site == "kaiju-agent" else " 2>&1 || echo " + q(QFAIL)
    if site == "setonix":
        cmd += "; echo %s; sacct -X -u %s -S now-2days -o %s" % (q(SACCT_MARK), u, q(SACCT))
    # One shared listing per floor, filtered here: a made-up task or job id cannot force another login.
    out, age = cached(site, lambda: remote_text(site, cfg, ctx, cmd))
    # A failed query must not read as "the job has gone": wait would return and Claude would fetch a running run.
    need(QFAIL not in out.split(SACCT_MARK)[0], "the %s queue query failed %d s ago and is retried after %d s; tell "
         "the member if it keeps failing." % (site, age, SITES[site]["floor"]) + untrusted(clean(out, 1000), site))
    return out, age


def state_of(site, out, age, jid):
    """None once the job or task has stopped."""
    if site == "kaiju-agent":
        st = [t[1] for t in parse_agent(out, jid)[0]]
        st = st[0] if st[:1] == ["running"] else None
    else:
        st = job_state(site, job_lines(site, out, jid, queue_only=True), jid) if jid else None
    # A listing cached before our own submit or task returned cannot show it yet: it has not finished.
    if st is None and jid and SUBMITS.get((site, job_key(jid)), 0) > time.time() - age:
        st = "SUBMITTED"
    return st


def query(cfg, site, jid, ctx):
    """(text, age, state): state is None once the job or task has stopped."""
    out, age = listing(cfg, site, ctx)
    return out, age, state_of(site, out, age, jid)
