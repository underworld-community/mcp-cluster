#!/usr/bin/python3 -I
"""Runs the three kaiju-agent scripts in uw3hpc/agent locally under bash, with fake Slurm, setsid and claude-agent:
start, status, busy and missing projects, cancel. No network.

usage: agent_sim.py [ROOT]      ROOT is the folder holding hpc_mcp.py (default: this checkout)
"""
import os
import shlex
import subprocess
import sys
import time
import uuid

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import testkit  # noqa: E402 (needs the path above)

testkit.use(sys.argv[1] if len(sys.argv) > 1 else None)
from uw3hpc import sites  # noqa: E402 (needs ROOT on sys.path)
from uw3hpc.scheduler import parse_agent  # noqa: E402

W = testkit.workdir("agentsim")
home, share, fb = W + "/home", W + "/share", W + "/bin"
for d in (home + "/work/proj", fb):
    os.makedirs(d)
os.makedirs(share + "/" + "jdoe-agent/outbox")
fakes = {
    "timeout": '#!/bin/sh\nshift\nexec "$@"\n',
    "setsid": '#!/usr/bin/python3\nimport os, sys\nos.setsid()\nos.execvp(sys.argv[1], sys.argv[1:])\n',
    "squeue": '#!/bin/sh\necho "job 77 RUNNING 1:00"\necho "job 78_[2-9%2] PENDING 0:00"\n',
    "id": '#!/bin/sh\n[ "$1" = -un ] && { echo jdoe-agent; exit 0; }\nexec /usr/bin/id "$@"\n',
    # macOS find has no -printf; emulate just what AGENT_STATUS asks for (find DIR -type f -printf '%s\n').
    "find": '#!/bin/sh\ncd "$1" && /usr/bin/find . -type f | while read -r f; do wc -c < "$f" | tr -d " "; done\n',
    "claude-agent": '#!/bin/sh\ncat > "$HOME/seen-prompt"; echo "$@" > "$HOME/seen-args"\n'
                    'sleep "$(cat "$HOME/sleep" 2>/dev/null || echo 1)"; echo "{}"\n',
}
for n, body in fakes.items():
    with open(fb + "/" + n, "w") as f:
        f.write(body)
    os.chmod(fb + "/" + n, 0o755)
env = {"PATH": fb + ":/usr/bin:/bin", "HOME": home, "LANG": "C"}


def remote(script, args, data=None):
    s = script.replace("/home/agent-share", share)
    words = ["timeout", "120", "bash", "-c", shlex.quote(s), "hpc"] + [shlex.quote(a) for a in args]
    p = subprocess.run(["/bin/sh", "-c", " ".join(words)], input=(data or "").encode(), capture_output=True,
                       env=env, timeout=30)
    return p.stdout.decode(), p.stderr.decode()


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


ok = True


def check(label, cond, detail=""):
    global ok
    print("%s %s %s" % ("PASS" if cond else "FAIL", label, detail if not cond else ""))
    ok &= bool(cond)


tid, sess = time.strftime("t%Y%m%d-%H%M%S-") + "ab12", str(uuid.uuid4())
write(home + "/sleep", "1")
out, err = remote(sites.AGENT_START, (tid, "proj", sess, fb + "/claude-agent"), "PROMPT LINE 1\nline 2\n")
check("start prints OK", ("OK %s %s" % (tid, sess)) in out.splitlines(), out + err)
time.sleep(0.3)
td = home + "/.hpc-tasks/" + tid
check("pid written at once", os.path.getsize(home + "/.hpc-tasks/%s/pid" % tid) > 0)
check("task dir files", all(os.path.exists(td + "/" + f) for f in ("prompt", "project", "session", "pid", "start")))
check("task dir is 0700", oct(os.stat(td).st_mode & 0o777) == "0o700", oct(os.stat(td).st_mode))
check("outbox created", os.path.isdir(share + "/jdoe-agent/outbox/" + tid))
out, err = remote(sites.AGENT_STATUS, ())
t = parse_agent(out, tid)[0]
check("status running", t and t[0][1] == "running", out + err)
time.sleep(2)
check("agent got prompt on stdin", read(home + "/seen-prompt") == "PROMPT LINE 1\nline 2\n")
check("agent args", read(home + "/seen-args").split() == ["-p", "--session-id", sess, "--add-dir",
      share + "/jdoe-agent/outbox/" + tid, "--output-format", "json"], read(home + "/seen-args"))
write(share + "/jdoe-agent/outbox/%s/SUMMARY.md" % tid, "done\n")
os.makedirs(share + "/jdoe-agent/outbox/%s/plots" % tid)
write(share + "/jdoe-agent/outbox/%s/plots/a.png" % tid, "x" * 10)
out, err = remote(sites.AGENT_STATUS, ())
tasks, jobs = parse_agent(out, tid)
check("status done rc 0", tasks and tasks[0][1:3] == ("done", "0") and tasks[0][5] == sess and tasks[0][6] == "proj",
      out + err)
check("outbox counted, no names", tasks and tasks[0][7:] == ("2", "15") and "SUMMARY" not in out, out)
check("jobs listed without names, a pending array range too", jobs == [("77", "RUNNING", "1:00"), (
    "78_[2-9%2]", "PENDING", "0:00")], jobs)
write(home + "/sleep", "30")
tid2, sess2 = time.strftime("t%Y%m%d-%H%M%S-") + "cd34", str(uuid.uuid4())
out, err = remote(sites.AGENT_START, (tid2, "proj", sess2, fb + "/claude-agent"), "long\n")
check("second start OK", ("OK %s %s" % (tid2, sess2)) in out.splitlines(), out + err)
tid3 = time.strftime("t%Y%m%d-%H%M%S-") + "ef56"
out, err = remote(sites.AGENT_START, (tid3, "proj", str(uuid.uuid4()), fb + "/claude-agent"), "x\n")
check("busy refused", ("ERR busy " + tid2) in out, out + err)
out, err = remote(sites.AGENT_START, (tid3, "nope", str(uuid.uuid4()), fb + "/claude-agent"), "x\n")
check("missing project refused", "ERR no-project" in out, out + err)
pid = int(read(home + "/.hpc-tasks/%s/pid" % tid2))
out, err = remote(sites.AGENT_CANCEL, (tid2,))
check("cancel OK", ("OK " + tid2) in out.splitlines(), out + err)
time.sleep(0.5)
alive = subprocess.run(["/bin/kill", "-0", str(pid)], capture_output=True).returncode == 0
check("task process group killed", not alive)
out, err = remote(sites.AGENT_STATUS, ())
tasks = parse_agent(out)[0]
check("list shows done and cancelled", sorted(t[1] for t in tasks) == ["cancelled", "done"], out + err)
out, err = remote(sites.AGENT_CANCEL, (tid,))
check("cancel finished task refused", "ERR finished" in out, out + err)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
