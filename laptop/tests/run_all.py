#!/usr/bin/python3 -I
"""Every offline test, in order: test_unit (seconds), agent_sim (seconds), test_scheduler (15 s), harness (about 2
minutes), test_docs (README.md and ADMIN.md against their sources, always this checkout's), then test_sshd, which skips
itself unless UW3HPC_SSHD_TEST=1 (a real sshd on 127.0.0.1, seconds).

usage: /usr/bin/python3 -I tests/run_all.py [ROOT] [--claude CLI]...
  ROOT          the folder holding hpc_mcp.py (default: this checkout)
  --claude CLI  also run claude_runs.py with that claude binary, once from the checkout and once installed: real
                Claude Code runs that spend tokens, so never by default
Set UW3HPC_TEST_DIR to keep the work folders. Exit 1 if anything failed.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
PY = "/usr/bin/python3"


def main(argv):
    clis = [b for a, b in zip(argv, argv[1:]) if a == "--claude"]
    rest = [a for i, a in enumerate(argv) if a != "--claude" and (i == 0 or argv[i - 1] != "--claude")]
    if any(a.startswith("-") for a in rest) or len(rest) > 1:
        return print(__doc__.strip()) or 2
    root = rest[:1]
    runs = [(n, [PY, "-I", os.path.join(HERE, n + ".py")] + ([] if n == "test_docs" else root))
            for n in ("test_unit", "agent_sim", "test_scheduler", "harness", "test_docs", "test_sshd")]
    for cli in clis:
        runs += [("claude_runs %s %s" % (cli, how), [PY, "-I", os.path.join(HERE, "claude_runs.py"), cli]
                  + (root or [os.path.dirname(HERE)]) + flag)
                 for how, flag in (("checkout", []), ("installed", ["--installed"]))]
    summary = []
    for name, argv_ in runs:
        print("==== %s" % name, flush=True)
        t0 = time.time()
        rc = subprocess.call(argv_)
        summary.append("%-4s %s (%.0f s)" % ("ok" if rc == 0 else "FAIL", name, time.time() - t0))
    if os.environ.get("UW3HPC_SSHD_TEST") != "1":
        summary.append("skip test_sshd's checks (set UW3HPC_SSHD_TEST=1: it opens a port on 127.0.0.1)")
    if not clis:
        summary.append("skip claude_runs (pass --claude CLI to run real Claude Code)")
    print("==== summary\n" + "\n".join(summary))
    return 1 if any(x.startswith("FAIL") for x in summary) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
