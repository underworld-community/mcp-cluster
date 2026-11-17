"""uw3-hpc, the local stdio MCP server; hpc_mcp.py beside this folder is the entry point. The guide is README.md at
the top of the mcp-cluster repository.

Modules from the bottom up: sites (what an admin edits), util, config, transport (ssh, rsync, lockout), scheduler,
files, tools, protocol (JSON-RPC) and admin (install, doctor, reset, selftest).
"""
VERSION = "1.2.0"
