#!/usr/bin/python3 -I
"""Opt-in: one bounded `claude -p --model haiku` run against a real server, registered as members register it
(env -i). Every key is missing or not loaded, so the server refuses before any connection. This spends tokens and
uses the account's Claude login, so run_all.py runs it only when given --claude.

usage: claude_runs.py CLI [ROOT] [--installed] [--plain] [--wrap]
  CLI          the claude binary to test
  ROOT         the folder holding hpc_mcp.py (default: this checkout)
  --installed  install ROOT into the temp home first and register that copy
  --plain      register without env -i (the server gets SSH_AUTH_SOCK=/nonexistent instead)
  --wrap       log every JSON-RPC line between the CLI and the server (tee_mcp.py) into the work folder
Prints a JSON summary; exit 1 unless every check passed.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
import testkit  # noqa: E402 (needs the path above)

opts = [a for a in sys.argv[1:] if a.startswith("--")]
pos = [a for a in sys.argv[1:] if not a.startswith("--")]
if not pos or set(opts) - {"--installed", "--plain", "--wrap"}:
    sys.exit(__doc__)
cli = pos[0]
ROOT = testkit.use(pos[1] if len(pos) > 1 else None)
from uw3hpc import admin  # noqa: E402 (needs ROOT on sys.path)

if os.path.lexists(admin.MANAGED):  # its allowlist filters --mcp-config servers too
    sys.exit("%s admits only the hpc installed in ~/.local/share/uw3-hpc, so this run's temp server would not load: "
             "run claude_runs on a Mac without it" % admin.MANAGED)

W = testkit.workdir("claude")
CH = W + "/home"
CFG = CH + "/.config/uw3-hpc/config.json"
TOOLS8 = {"mcp__hpc__" + n for n in ("status", "wait", "get", "submit", "put", "run", "cancel", "task")}

os.makedirs(CH + "/.ssh", mode=0o700)
os.makedirs(CH + "/hpc/downloads")
open(CH + "/hpc/downloads/.uw3-hpc-root", "w").close()
subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "throwaway-claude-test", "-C", "throwaway",
                "-f", CH + "/.ssh/id_setonix"], check=True, stdin=subprocess.DEVNULL)
os.makedirs(os.path.dirname(CFG))
with open(CFG, "w") as f:
    json.dump({"sites": {
        "gadi": {"user": "ab1234", "key": "~/.ssh/id_gadi_missing", "project": "m18",
                 "base": "/scratch/m18/ab1234/hpc", "storage": "scratch/m18+gdata/m18"},
        "setonix": {"user": "jdoe", "key": "~/.ssh/id_setonix", "project": "pawsey1147",
                    "base": "/scratch/pawsey1147/jdoe/hpc"},
        "kaiju": {"user": "jdoe", "key": "~/.ssh/id_kaiju_missing", "base": "/home/jdoe/hpc"},
        "kaiju-agent": {"user": "jdoe-agent", "key": "~/.ssh/id_agent_missing"}}}, f)
os.chmod(CFG, 0o600)
entry = os.path.join(ROOT, "hpc_mcp.py")
if "--installed" in opts:
    src = W + "/src"  # a committed clone of its own, as install refuses anything else
    testkit.git_copy(ROOT, src, admin.SHIPPED)
    p = subprocess.run([testkit.PY, "-I", src + "/hpc_mcp.py", "install", "--home", CH], capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "HOME": CH}, timeout=60)
    if p.returncode:
        sys.exit("install failed:\n" + p.stdout + p.stderr)
    entry = CH + "/.local/share/uw3-hpc/hpc_mcp.py"
testkit.managed_copy(ROOT, CH)  # serve refuses every call without it
# --home keeps the server's cache and log in the temp home; under env -i no agent socket is inherited.
args = ["-I", entry, "serve", "--config", CFG, "--home", CH]
srv = {"command": "/usr/bin/env", "args": ["-i", testkit.PY] + args}
if "--plain" in opts:
    srv = {"command": testkit.PY, "args": args, "env": {"SSH_AUTH_SOCK": "/nonexistent"}}
if "--wrap" in opts:
    srv["args"] = ["-I", os.path.join(testkit.HERE, "tee_mcp.py"), W + "/rpc.log", srv["command"]] + srv["args"]
    srv["command"] = testkit.PY
with open(W + "/mcp-hpc.json", "w") as f:
    json.dump({"mcpServers": {"hpc": srv}}, f)
with open(W + "/settings-allow-status-submit.json", "w") as f:
    json.dump({"permissions": {"allow": ["mcp__hpc__status", "mcp__hpc__submit"]}}, f)

prompt = ("Call the hpc status tool with site gadi. Then call the hpc submit tool with site gadi, run r1, one job "
          "(script j.sh, walltime 01:00:00, cores 4) and total_core_hours 4. Call nothing else. Finally quote both "
          "tool results verbatim.")
env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
cmd = [cli, "-p", prompt, "--model", "haiku", "--max-turns", "4", "--mcp-config", W + "/mcp-hpc.json",
       "--strict-mcp-config", "--settings", W + "/settings-allow-status-submit.json",
       "--setting-sources", "project,local", "--tools", "", "--no-session-persistence",
       "--output-format", "stream-json", "--verbose"]
log = CH + "/.cache/uw3-hpc/server.log"
t0 = time.time()
p = subprocess.Popen(cmd, cwd=W, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True)
lines, err = [], []
threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True).start()
timer = threading.Timer(240, p.kill)
timer.start()
for line in p.stdout:
    lines.append((time.time() - t0, line))
rc = p.wait()
timer.cancel()
with open(W + "/claude.jsonl", "w") as f:  # kept with UW3HPC_TEST_DIR
    f.writelines(x for _, x in lines)

s = {"cli": cli, "version": subprocess.run([cli, "--version"], capture_output=True, text=True).stdout.strip(),
     "registered": [srv["command"]] + srv["args"], "rc": rc, "seconds": round(time.time() - t0, 1), "tool_uses": [],
     "results": []}
for t, line in lines:
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "system" and ev.get("subtype") == "init":
        s["init_s"] = round(t, 2)
        s["mcp_servers"] = ev.get("mcp_servers")
        s["hpc_tools"] = sorted(x for x in ev.get("tools", []) if x.startswith("mcp__hpc__"))
    elif ev.get("type") == "assistant":
        s["tool_uses"] += [(c["name"], c.get("input")) for c in ev["message"].get("content", []) if c.get(
            "type") == "tool_use"]
    elif ev.get("type") == "user" and isinstance(ev["message"].get("content"), list):
        for c in ev["message"]["content"]:
            if c.get("type") == "tool_result":
                body = c.get("content")
                if isinstance(body, list):
                    body = "".join(b.get("text", "") for b in body if isinstance(b, dict))
                s["results"].append({"is_error": c.get("is_error"), "text": (body or "")[:400]})
    elif ev.get("type") == "result":
        s["denials"] = [d.get("tool_name") for d in ev.get("permission_denials") or []]
        s["final"] = str(ev.get("result"))[:300]
s["server_log"] = open(log).read().splitlines() if os.path.exists(log) else []
s["checks"] = {
    "connected": any(x.get("name") == "hpc" and x.get("status") == "connected" for x in s.get("mcp_servers") or []),
    "8 tools visible": set(s.get("hpc_tools", [])) == TOOLS8,
    "init under 5 s (no discover stall)": s.get("init_s", 99) < 5,
    "status returned the key error": any(r["is_error"] and re.search(r"key .* not found", r["text"])
                                         for r in s["results"]),
    "submit refused in -p despite the allow rule": "mcp__hpc__submit" in s.get("denials", []) and not any(
        "\tsubmit\t" in x for x in s["server_log"]),
    "status reached the server and was refused there": any("\tstatus\tgadi\t-\trefused\t" in x
                                                           for x in s["server_log"])}
s["stderr"] = "".join(err)[:300]
if "--wrap" in opts:
    s["rpc_log"] = (open(W + "/rpc.log").read() if os.path.exists(W + "/rpc.log") else "")[:4000]
print(json.dumps(s, indent=1))
sys.exit(0 if all(s["checks"].values()) else 1)
