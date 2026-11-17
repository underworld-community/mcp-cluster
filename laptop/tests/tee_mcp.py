#!/usr/bin/python3 -I
"""Pass-through that logs each JSON-RPC line (timestamped, truncated) between Claude and the real server.

usage: tee_mcp.py LOG COMMAND...      (claude_runs.py --wrap puts it in the registration)
"""
import subprocess
import sys
import threading
import time

LOG, cmd, t0, lk = sys.argv[1], sys.argv[2:], time.time(), threading.Lock()
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)


def log(d, line):
    with lk, open(LOG, "a") as f:
        f.write("%.3f %s %s\n" % (time.time() - t0, d, line.decode(errors="replace").rstrip("\n")[:240]))


def up():
    for line in p.stdout:
        log("<", line)
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()


threading.Thread(target=up, daemon=True).start()
for line in sys.stdin.buffer:
    log(">", line)
    p.stdin.write(line)
    p.stdin.flush()
p.stdin.close()
sys.exit(p.wait())
