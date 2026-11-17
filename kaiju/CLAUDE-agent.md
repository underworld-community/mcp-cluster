# Kaiju agent account

You are running as @AGENT@, a Kaiju agent account that works for one member. Where the
"Kaiju cluster" notes above differ, these notes win for this account.

- `sbatch`, `srun`, `scancel` and `apptainer` run without asking, outside the sandbox,
  as @AGENT@. Run each as a plain single command, as above. Heavy work still goes to
  the compute nodes: `srun` for short runs, `sbatch` for anything longer; keep
  `apptainer` on the login node to quick checks.
- `squeue`, `sinfo` and `scontrol show` work as above. `salloc`, `sacct`, `sstat`
  and `seff` do not.
- Work in `@HOME@/work`. Startup files, `~/.claude` and `~/.config` are root-owned and
  read-only to you; that is deliberate, so do not try to work around it.
- Compute nodes have no internet. On the login node, sandboxed commands reach only the
  package and code hosts the policy lists (PyPI, GitHub, conda, prefix.dev). Fetch
  what a job needs before submitting it.
- `git push` is disabled for this account. To hand results or patches to the member,
  put them in `/home/agent-share/@AGENT@/outbox`, then run
  `chmod -R a+rX /home/agent-share/@AGENT@/outbox`: your umask is 027, so the member
  cannot read them otherwise. Everyone on Kaiju can read the outbox, so put nothing
  private there. Say what you left there.
- Never read, print or copy `~/.config/kaiju-agent` or any token, key or credential.
