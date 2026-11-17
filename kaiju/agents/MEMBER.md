# Your Kaiju agent account

An agent account (`<you>-agent`, e.g. `jdoe-agent`) is a second Kaiju account where Claude works
for you with fewer prompts: it submits jobs, runs `srun` and `apptainer` and edits its own files
without asking. It has no sudo and none of your keys; the admin can switch it off at once.
Claude in your own account: [../README.md](../README.md). Claude on your laptop can also start tasks
here once its Kaiju tests pass ([laptop link](../../README.md#kaiju-agent-tasks)).

## The rules

The separate account protects you only while nothing the agent wrote runs as you:

- **Never run the agent's code, jobs or repositories as yourself**, on Kaiju or your laptop: not
  its scripts or job files, not `pip install` of what it built, not even `git status` in a
  repository it wrote (a repo's `.git/config` can run commands). Read what it made, then take it in
  as a patch (below).
- **Never put your own keys or tokens in it**: no ssh keys, GitHub tokens, API keys, `.netrc` or git
  credentials. Its only credential is the `claude setup-token` token.
- **Never `su`, `sudo -u` or `sudo -i` into it.** Use a fresh `ssh kaiju-agent` from your laptop
  (ssh from inside Kaiju is refused): a process it leaves on a terminal you switched from can type
  commands into your own shell, which has sudo.
- **Never `/login` there.** A full login hands the agent your whole claude.ai account (projects,
  connectors, remote sessions). The setup token can only run Claude.

## Get one

On your laptop, make a new key just for this, with a passphrase:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_kaiju_agent -C "<you>-agent"
```

Send the admin the one line in `~/.ssh/id_ed25519_kaiju_agent.pub` and where you connect from
(campus, ANU VPN, home), so the key can be limited to those places. Don't reuse your Kaiju key: the
setup refuses a key your own account accepts, and a separate one can be cut off without touching
your own access.

## One-time setup

1. In `~/.ssh/config` on your laptop, above any `Host *` block (the first match wins):

   ```
   Host kaiju-agent
       HostName kaiju.anu.edu.au
       User <you>-agent
       IdentityFile ~/.ssh/id_ed25519_kaiju_agent
       IdentitiesOnly yes
       ForwardAgent no
       ForwardX11 no
       ClearAllForwardings yes
       ControlMaster no
       ControlPath none
   ```

   `ControlPath none` stops it riding on an open `kaiju` connection that has forwarding on. VS Code
   Remote-SSH needs forwarding, so use a terminal.
2. On your laptop, run `claude setup-token` (Pro, Max, Team or Enterprise plan). It signs in
   through your browser and prints a token valid for a year; copy it. A Team or Enterprise token
   works only if the organization sets no Claude Code settings in claude.ai (they would replace
   Kaiju's agent rules).
3. Store it on Kaiju without it showing on screen or in shell history:

   ```bash
   ssh kaiju-agent
   install -d -m 700 ~/.config/kaiju-agent
   (umask 077; IFS= read -rs T; printf '%s\n' "$T" > ~/.config/kaiju-agent/oauth-token)
   ```

   Paste the token, press Enter. `ls -l ~/.config/kaiju-agent/oauth-token` should show
   `-rw-------` and your agent name. To replace it, run the same lines with a new token.

## Every time

```bash
ssh kaiju-agent
tmux new -A -s claude       # creates the session, or reattaches to it
cd ~/work/<project>         # first time: cd ~/work, and ask Claude to clone it
claude-agent
```

Two logins: `ssh kaiju-agent` from the laptop gets you onto Kaiju (run
`ssh-add -t 12h ~/.ssh/id_ed25519_kaiju_agent` there once a day and it stops asking), and
`claude-agent` signs Claude in with the token, with nothing to type. Use `claude-agent`, never
`claude`: plain `claude` has no token and asks you to log in, which must never happen in this
account (`/exit` instead). Not found? `module load claude-code`.
`/status` must show `Enterprise managed settings (helper)` and no "Login method", "Organization" or
"Email" lines (those mean a full login), and "Auth token: CLAUDE_CODE_OAUTH_TOKEN". Ignore its warnings about
`~/.local/bin`: Claude runs from the shared install on purpose. `(remote)`: `/exit`, and use a token from an account whose
organization sets no Claude Code settings. If Claude asks you to log in, the token is missing or
wrong: `/exit` and redo step 3. Detach with Ctrl-b then d; come back with
`ssh kaiju-agent` and `tmux attach -t claude`.

## What Claude can do here

| Action | Rule |
|---|---|
| Shell commands | **without asking**, in the sandbox: write only in the project, `~/work` and temp |
| `sbatch`, `srun`, `scancel`, `apptainer` | **without asking**, outside the sandbox, as the agent |
| `squeue`, `sinfo`, `scontrol show` | without asking |
| Edit files in the project or `~/work` | without asking; anywhere else, asks you |
| Network from shell commands | GitHub, PyPI and conda only; other hosts are refused |
| Web fetches | a few documentation sites without asking; others ask |
| Read the token, `~/.ssh` and other credential files; change shell startup files, git config, `~/.claude` settings, `/opt/cluster` | refused |

The admin sets these rules; you cannot add your own allow rules.

## Code in, results out

- **Code in**: Claude clones from GitHub over https into `~/work`; push your branch from your
  laptop, then ask Claude to `git pull`. ssh git and pushes from the agent fail. A private repo
  goes in as a bundle, which carries commits only (no `.git/config`, whose remote URL can hold a
  token, and no `.env` or other untracked files). On your laptop:
  `git -C myrepo bundle create /tmp/myrepo.bundle --all`, then
  `rsync -P /tmp/myrepo.bundle kaiju-agent:work/`; then ask Claude to
  `git clone ~/work/myrepo.bundle ~/work/myrepo`.
- **Results out**: ask Claude to put them in `/home/agent-share/<you>-agent/outbox/`, which anyone
  on Kaiju can read (so nothing private). A laptop-started task's `outbox/<task id>/` comes back
  with the laptop `get` tool (run = the task id), which drops links, odd names and files that would
  steer Claude. Anything else, by hand: with the agent key, never through your own
  account, into a folder outside any project (no `-l`, so the agent's links are not copied):
  `rsync -rtP --max-size=200m --exclude='.*' --exclude='[Cc][Ll][Aa][Uu][Dd][Ee]*.[Mm][Dd]' --exclude='[Aa][Gg][Ee][Nn][Tt][Ss].[Mm][Dd]' kaiju-agent:/home/agent-share/<you>-agent/outbox/ ~/hpc/downloads/kaiju-agent/`
- **Code changes back**: ask for `git format-patch` files in the outbox. Read them, then in your
  own clone `git am /path/to/*.patch` and push yourself.

## The Underworld3 loop

Ask Claude to work like this (details in the
[container guide](https://github.com/underworld-community/uw3-hpc-install-run/blob/main/kaiju/container/README.md)):

1. Fetch everything on the login node: compute nodes have no internet, so a job cannot
   `pip install` or `git clone`.
2. Build in the container on the login node, within the account's cap:
   `module load underworld3-container/development`, then `pip install --target` into `~/work`
   inside `apptainer exec` (or an Apptainer overlay).
3. Copy `/opt/cluster/software/containers/underworld3/kaiju_container_job.sh` into the project and
   submit it with `sbatch`, passing `CONTAINER`, `SCRIPT` and `EXTRA_PKGS`.
4. Read `uw3c_<jobid>.out` and `.err`, fix, repeat.

## Limits and cost

- On the login node everything the account runs shares one cap, by default 8 CPUs and 32 GB. Over
  the CPU cap it slows down; over the memory cap the kernel kills its largest process, which can be
  Claude. Need more? Ask the admin.
- Slurm has no fair-share on Kaiju, so the agent can fill the queue. Tell it how much it may use
  (e.g. in the project's `CLAUDE.md`: "at most 2 nodes, jobs under 4 h"), and check
  `squeue -u <you>-agent` now and then.
- The agent uses your Claude plan and its 5-hour and weekly limits; several sessions use them up
  faster. Your plan's data terms apply (Pro or Max: check claude.ai/settings/data-privacy-controls).

## Stop everything

In the agent account (for one laptop-started task, the laptop `cancel` tool is enough):

```bash
pkill -u $USER -f claude   # every Claude, including tasks your laptop started (they run outside tmux)
scancel -u $USER           # all its jobs, once nothing is left to submit more
tmux kill-server           # everything else started in tmux
exit
```

Tell the admin at once if you see jobs, files or network use you did not expect, or your
agent key or token may have leaked. Suspending the account ends its logins, processes and jobs on
every node, but a leaked token works anywhere: also try to revoke it in claude.ai settings (it is
not yet known whether that works before it expires).
