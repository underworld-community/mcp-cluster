#!/usr/bin/python3
"""uw3-hpc: one local stdio MCP server through which Claude Code on a laptop reaches Gadi (NCI), Setonix (Pawsey),
Kaiju and the member's Kaiju agent account; only the laptop connects. Python 3.9 stdlib only; macOS, and Linux
(Ubuntu, Debian) on trial.
serve-codex and doctor-codex are the read-only server (status, wait, get) and its checks for OpenAI's Codex CLI.

  hpc_mcp.py serve | serve-codex | doctor | doctor-codex [--config PATH] | install | reset SITE | selftest
  --home DIR replaces the account's home directory in every mode; doctor and serve look for /Library and /etc under
  it, and serve accepts a policy file the account owns there (tests only).
The guide is README.md at the top of the mcp-cluster repository.
"""
import os
import pwd
import sys

# python3 -I leaves this file's folder off sys.path. Appended, not prepended, so a file dropped beside this one
# cannot stand in for a standard module; realpath, so a linked entry point still finds its own package.
sys.path.append(os.path.dirname(os.path.realpath(__file__)))
# No __pycache__: install's folders are read-only, and doctor fails on any file install did not put there.
sys.dont_write_bytecode = True

from uw3hpc import admin, protocol, util  # noqa: E402 (needs the path above)
from uw3hpc.sites import SITES  # noqa: E402


def main(argv):
    flags = {a: b for a, b in zip(argv, argv[1:]) if a in ("--config", "--home")}
    pos = [a for i, a in enumerate(argv) if a not in flags and (i == 0 or argv[i - 1] not in flags)]
    mode = (pos + [""])[0]
    # Never $HOME, so install, serve and doctor agree on where the config and state live.
    util.set_home(flags.get("--home") or pwd.getpwuid(os.getuid()).pw_dir)
    admin.SYSROOT = util.HOME if "--home" in flags else ""
    if mode in ("serve", "serve-codex") and not os.environ.get("SSH_AUTH_SOCK"):  # started under env -i (REGISTER)
        os.environ["SSH_AUTH_SOCK"] = admin.agent_sock()
    util.READ_ONLY = mode == "serve-codex"
    cfg, usage = flags.get("--config") or util.CONFIG, lambda: print(__doc__.strip()) or 2
    return {"serve": lambda: protocol.serve(cfg, admin.managed_gate), "doctor": lambda: admin.doctor(cfg),
            "serve-codex": lambda: protocol.serve(cfg, admin.codex_gate),
            "doctor-codex": lambda: admin.doctor(cfg, codex=True),
            "install": admin.install,
            "selftest": admin.selftest,
            "reset": lambda: admin.reset(pos[1]) if pos[1:2] and pos[1] in SITES else usage()}.get(mode, usage)()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
