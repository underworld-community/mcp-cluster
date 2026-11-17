# Agent accounts: admin runbook

`kaiju-agent` makes and manages `<member>-agent` accounts (uid = gid in 7000-7999, group
`kaiju-agents` gid 7000). Run it as your `-adm` account on the login node from a fresh ssh, in
this directory. Keep a second `-adm` session open while sshd is being changed.

## Set up: the canary first

The admin's own agent account goes first, so the whole path (policy, account, laptop `task`) is
tested before anyone else depends on it. The admin is then both admin (`<admin>-adm`) and member
(`<admin>`). Steps 1-3 are once per cluster; 4-8 for each agent.

1. **Precheck** (read-only): `./kaiju-agent precheck`. Note `ROUTE=nis|local` and `ROOT_SQUASH`.
   Stop if the uid block 7000-7999 is in use or a `*-agent` name exists. If
   `AllowUsers`/`AllowGroups` is set, first add `kaiju-agents` there by hand.
2. **Baseline**, once per cluster: `./kaiju-agent baseline --route <ROUTE> --dry-run`, read the
   diffs, then run it without `--dry-run`. It adds the `kaiju-agents` group, the login node's sshd
   `Match User *-agent` block and internal `DenyUsers`, `DenyUsers *-agent` on n1-n8,
   `/etc/ssh/authorized_keys/`, the polkit no-linger rule, `/home/agent-share` and
   `/etc/kaiju-agents/`. On route nis it shows `make -n -C /var/yp` and asks before publishing: a
   rebuild publishes every pending `/etc` change, not only ours.
3. **Policy**: back up, `sudo cp -a /etc/claude-code /etc/claude-code.bak-$(date +%Y%m%d)`, then
   `../kaiju_claude_install.sh policy`. The helper needs the `kaiju-agents` gid. `policies/human.json`
   is the policy human accounts already have, so they see no change except that Claude refuses
   `-adm` accounts and root, and the module's help text. Undo on the login node:
   `sudo install -m 0644 -o root -g root /etc/claude-code.bak-<date>/managed-settings.json /etc/claude-code/`.
4. **Create**: on your laptop, make a NEW key with a passphrase,
   `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_kaiju_agent`, and copy its public half over:
   `scp ~/.ssh/id_ed25519_kaiju_agent.pub kaiju-adm:<member>-agent.pub`. Then
   `./kaiju-agent create <member> --pubkey ~/<member>-agent.pub --dry-run`, then without
   `--dry-run`. Defaults: the next uid from 7001, `--cpu 800% --mem 32G --tasks 4096`. If `/home` is
   root-squashed, create stops after the account and prints a root script: run it on the NFS
   server, then rerun the same command. The key goes in last.
5. **Member**: as the member, on their laptop and Kaiju, follow [MEMBER.md](MEMBER.md) and the
   steps create prints. Then add `kaiju-agent` to the laptop's `~/.config/uw3-hpc/config.json`
   (user `<member>-agent`, key `~/.ssh/id_ed25519_kaiju_agent`) for the `task` tool.
6. **Checks**: `./kaiju-agent audit <member>-agent` must say `audit: clean`. Run the sshd `-T` and
   sysfs commands create printed, then go through [CHECKS.md](CHECKS.md).
7. **Off switch**: rehearse it once. `./kaiju-agent suspend <member>-agent` empties the key
   file, sets `chage -E 0`, runs `loginctl terminate-user`, `pkill -KILL` on the login node and
   every reachable node, and `scancel -u`. `./kaiju-agent resume <member>-agent` restores the key from
   `/etc/kaiju-agents/keys/` and the expiry date. If the token may have leaked, also revoke it in
   claude.ai.
8. **Laptop `task`**: from laptop Claude, a short `task` on site `kaiju-agent`, then `wait` and
   `get` its outbox (open live tests 5, 6 and the agent half of 10 in
   [../../ADMIN.md](../../ADMIN.md#open-live-tests)).

### Last: human accounts

Once the canary passes, and after telling everyone who uses Claude on Kaiju:

1. **Stricter human policy:** in the laptop repo, `cp kaiju/policies/human-next.json
   kaiju/policies/human.json`, drop the "Coming" line under the table in
   [../README.md](../README.md), commit, send a new bundle, then `git pull` and rerun `policy`.
   It turns auto mode off and refuses edits to `~/.claude.json` and `~/.claude/CLAUDE.md`. Check:
   `helper_as nobody` shows `"disableAutoMode": "disable"`, and Shift+Tab in a human session never
   reaches auto.
2. **Other members:** anyone who needs sudo gets an `-adm` account and their everyday account loses
   it; then steps 4-7 for their agent, with their acceptance email ([CHECKS.md](CHECKS.md)
   section 6).

`./kaiju-agent list` shows the registry (`/etc/kaiju-agents/registry.tsv`) with key state,
login-node processes and queued jobs. `squeue` cuts names to 8 characters; use
`squeue -O jobid,username:16,name,state,timeused,nodelist`.

## Rules

- `baseline` and `create` are safe to rerun. Each edited file is backed up as
  `<file>.bak-YYYYMMDD-HHMMSS`. `sshd -t` runs before every reload; if it fails, that host's backup
  is restored and the script stops.
- A down node stops `baseline` and `create`. With `SKIP_NODES` the node is drained; once it is
  back, rerun `baseline` (and `create` on route local), `audit`, then
  `sudo scontrol update nodename=nN state=resume`.
- Never `su - <agent>`, `sudo -iu <agent>` or `ssh <agent>@localhost`: an agent process left on
  your tty can type into your shell (no TIOCSTI guard on kernel 4.18). The script runs agent-side
  commands only as `cd / && sudo -u <agent> setsid -w <tool> </dev/null`, and never runs or follows
  anything in an agent home as root.

## Deferred risks

Accepted until built (members also accept the cluster-specific host gaps, which the admin keeps
in private records and sends with the acceptance statements):

- **No egress filter by uid.** Anything the agent can read can leave through its excluded commands
  (`apptainer`, `srun`, jobs) or a prompt injection. Each member accepts this in writing.
  `kaiju-agent-netguard` is the optional start of a filter.
- **No Slurm agents partition, `job_submit.lua` or watchdog.** Agent jobs go to the normal queue
  with no per-agent limits (no accounting); only the admin's `scancel` caps them.
  `kaiju-agent-watchdog` is optional.
- **No `pam_namespace` for `/tmp`.** On the login node the agent shares `/tmp` and `/var/tmp`: it
  can fill them and read other users' world-readable temp files.
- **File permissions are the only wall between the agent and other users' files.** It can read
  whatever is world-readable (precheck lists readable homes and world-writable dirs).

## Laptop tasks

The [laptop link](../../README.md#kaiju-agent-tasks) (canary passed 2026-11-16) connects one way: the
laptop logs in to the agent account; nothing on Kaiju calls the laptop. Each `task` leaves state
that `audit` and offboarding should cover:

- `~/.hpc-tasks/<task id>/`: prompt, project, session, pid, start/end times, exit code,
  `out.json`, `err`.
- A detached `claude-agent -p` process per running task, in its own session outside tmux.
  `suspend` (`pkill -KILL -u`) stops it; `tmux kill-server` does not.
- `/home/agent-share/<agent>/outbox/<task id>/`, readable by everyone on Kaiju.
