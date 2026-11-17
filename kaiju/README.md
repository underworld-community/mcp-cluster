# Claude Code on Kaiju

Members first; admins: [Admin](#admin). The whole repository: [../README.md](../README.md)
(members) and [../ADMIN.md](../ADMIN.md) (admin).

## Quick start

First time only, in a plain ssh session (not tmux, so the login URL copies in one piece):

```bash
ssh kaiju
module load claude-code
which -a claude       # the first line must be /opt/cluster/software/claude-code/current/bin/claude
claude                # sign in, run /status (below), then /exit
```

Sign in with your own Claude account (Pro, Max, Team, Enterprise or a Console API key). Kaiju has
no browser: press `c` to copy the login URL, open it on your laptop and paste the code back. If `c`
copies nothing, see [Troubleshooting](#troubleshooting).

Then run `/status`: it must show `Enterprise managed settings (helper)`. `(remote)` means your
Team or Enterprise organization sets Claude Code settings in claude.ai, and those replace all of
Kaiju's rules (no sandbox, no refused files): `/exit`, then sign in with another account or ask the
organization's owner.

Every time after that:

```bash
ssh kaiju
tmux new -A -s claude       # creates the session, or reattaches to it
module load claude-code
cd ~/my-project             # a project directory, never your home
sudo -K                     # if your account has sudo: drop any cached sudo login
claude
```

> **Start `claude` from a project folder kept in git, never from your home directory.** Claude's
> commands can change anything in that folder without asking. From `$HOME`, a mistaken `rm` or
> `mv` can delete other projects, model outputs or your `~/.claude` history, and Claude can edit
> unprotected config files (`~/.condarc`, `~/.config/pip/`, `~/.spack/`, `~/.vimrc`) that carry
> into later sessions. In a project folder, damage stays there and git can undo it. Where you start
> `tmux` does not matter. For files elsewhere, still start in the project: Claude asks before
> editing outside it.

Leave it running with Ctrl-b then d; come back with `ssh kaiju` and `tmux attach -t claude`. Quit
Claude with `/exit`. Code: push from your laptop, `git pull` here. Results, from your laptop:
`rsync -avP kaiju:~/my-project/outputs/run42/ ./outputs/run42/`.

**Used Claude Code on Kaiju before?** If `which -a claude` lists `~/.local/bin/claude` first,
remove your copy: `rm ~/.local/bin/claude; rm -rf ~/.local/share/claude` (your sign-in in
`~/.claude` stays). Also check `~/.claude/settings.json` for old allow rules.

## What Claude can do here

| Action | Rule |
|---|---|
| Shell commands | run **without asking**, sandboxed: read anything your account can except the credential files below, write only to the project and temp, no `sudo` |
| Network from shell commands | asks once per new host; approve only hosts you trust (pypi.org, github.com) |
| `squeue`, `sinfo`, `scontrol show` | run without asking |
| `sbatch`, `srun`, `apptainer` | run without asking, outside the sandbox (for now; see [Your part](#your-part)) |
| `scancel` | asks every time |
| Edit or create files outside the project | asks |
| Read `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.netrc`, `~/.git-credentials`, `~/.config/gh`, `~/.docker`, `~/.apptainer`, `~/.pypirc` | refused |
| Change shell startup files, `~/.local/bin`, `~/.local/lib`, `~/bin`, git, tmux or module config, `~/.claude/settings.json`, anything under `/opt/cluster` | refused |
| Bypass-permissions mode, project hooks, `/feedback`, self-update | switched off |

Coming with the next policy change: auto mode off, and `~/.claude.json` and `~/.claude/CLAUDE.md`
refused.

The rules are root-owned, in `/etc/claude-code/` (`policies/human.json` for personal accounts),
and the refused and ask rules cannot be overridden. Claude also reads `/etc/claude-code/CLAUDE.md`,
on using Slurm and Underworld3 here. What you add to your own `~/.claude/settings.json` (allow
rules, excluded commands, allowed hosts) loosens things for you, so ask the admin first.

## Your part

- **`sbatch`, `srun` and `apptainer` run as you without asking**, outside the sandbox: the script,
  the Python it calls and any files it imports get your whole home directory. A stopgap while
  agent accounts are set up; for unattended work, use an agent account.
- **Everything Claude reads or prints is sent to Anthropic**, and it can read anything your account
  can, not only the project. Don't point it at other people's data or `! cat` secrets into the
  conversation. On a personal Pro or Max plan, check whether training on your chats is on at
  claude.ai/settings/data-privacy-controls.
- Start Claude in its own tmux session, not one where you use `sudo`, and never type a password
  into a Claude session.
- Don't approve changes to the rules above, even when Claude offers to make them.
- Model runs and test suites go through `sbatch`; on the login node only builds and short container
  checks.

## Agent accounts

An agent account (`<you>-agent`, e.g. `jdoe-agent`) is a separate account without sudo, where
Claude submits jobs and runs `srun` and `apptainer` without asking, and leaves results in an outbox
you can read. It signs in with a token from `claude setup-token` and starts with `claude-agent`,
not `claude`. To get and use one: [agents/MEMBER.md](agents/MEMBER.md#get-one). Admin steps:
[agents/README.md](agents/README.md).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| A Slurm command fails with `Unable to resolve "kaiju.anu.edu.au"` | Something was chained onto it (`; echo $?`, `&& ls`), so it ran in the sandbox; or it is not one of `squeue`, `sinfo`, `scontrol show`, `sbatch`, `scancel`, `srun`. `salloc` and `sacct` cannot work from Claude |
| `sbatch` (or another command the table allows) still asks | An `ask` rule in your own `~/.claude/settings.json` or the project's `.claude/settings*.json` (`/permissions` → Ask); delete it and restart `claude` |
| A `module load` or `spack load` seems to have no effect | Each of Claude's commands starts afresh: load it before starting `claude`, or in the same command that uses it. `spack find` works as normal |
| `module load claude-code` says the policy is missing | That node never got the policy; tell the admin |
| `claude` refuses to start and mentions the sandbox | bubblewrap or socat is missing on this node. Intended on a compute node; on the login node, tell the admin |
| `claude` refuses to start with `Kaiju Claude Code policy: ...` | The policy helper refused this account or is broken (the message says which): tell the admin. Intended from root or an `-adm` account |
| `claude-agent: no token at`, `must be mode 600`, `is a symlink`, `is not owned by` or `is empty` (agent accounts) | `~/.config/kaiju-agent/oauth-token` is missing, a link, not the agent's, not mode 600, or empty. Store it again as [agents/MEMBER.md](agents/MEMBER.md#one-time-setup) says, or `chmod 600` it |
| `squeue` asks for approval | The session started before the policy was installed; restart `claude` |
| Login URL won't copy, or the browser says the link is invalid | Sign in from a plain ssh session, not tmux; select the URL with the mouse; `/login` to retry |
| Can't select text in Claude's screen | macOS Terminal: Cmd+R toggles mouse reporting. iTerm2: hold Option while dragging. VS Code: enable `terminal.integrated.macOptionClickForcesSelection`, then Option-drag. Or `/export notes.txt` and copy the file |

## Admin

The files and where each is installed: [file layout](../ADMIN.md#file-layout).

### Do admin work from a separate account

Claude runs as the account that starts it, so an account that can `sudo` must never run it. Admins
keep two accounts:

- everyday, not in `wheel`: research and Claude;
- `-adm`, in `wheel`: admin work, reached only by a fresh `ssh <user>-adm@kaiju` from your own
  computer, never by `su` from the everyday account. The installer runs here, from this account's
  own clone of this repository.

### Install or update

```bash
cd mcp-cluster/kaiju
curl -fsSL https://downloads.claude.ai/claude-code-releases/latest; echo     # newest version
./kaiju_claude_install.sh 2.1.316
```

Once, on the login node only: `sudo dnf -y install bubblewrap socat`. Without them on the compute
nodes, Claude refuses to start there, which keeps it on the login node.

The script first pushes the policy to the login node and n1-n8 (`managed-settings.json`, which only
names the helper; `policy-helper` with its config; `policies/*.json`; `CLAUDE.md`). Then it
downloads the version, checks it (the release manifest's GPG signature against the fingerprint
pinned in the script, the binary's sha256 against the manifest), installs it root-owned as
`/opt/cluster/software/claude-code/<version>/bin/claude`, points `current` at it and installs the
`claude-code` modulefile. It stops at the first failure, before anything is made current.

- **Rules only:** edit `policies/human.json`, `policies/agent.json` or `CLAUDE.md`, run
  `./kaiju_claude_install.sh policy`, and restart open sessions. `policy` also installs the
  modulefile and the `claude-agent` wrapper, writes the human groups' gids into
  `/etc/claude-code/policy-helper.conf` and checks that `kaiju-agents` is gid 7000: rerun it after
  changing those groups.
- **Nodes:** a down node stops the install after the policy has gone to the rest. To go on without
  it: `SKIP_NODES="n5" ./kaiju_claude_install.sh 2.1.316`. Rerun `policy` once it is back, and
  after any node is reimaged.
- **If the helper fails** (missing or unreadable file, bad JSON, broken config), Claude refuses to
  start for everyone, with `Kaiju Claude Code policy: ...` or its own error. That is intended: no
  session beats one with looser rules. To let members back in while you fix it (no earlier commit
  needed):
  1. Suspend every agent account ([agents/README.md](agents/README.md)): the next step gives them
     the personal rules.
  2. On the login node, from this folder, through `/tmp` (root may not read your home on NFS):
     `install -m 0644 policies/human.json /tmp/kaiju-human.json && sudo install -m 0644 -o root -g root /tmp/kaiju-human.json /etc/claude-code/managed-settings.json`.
     Claude then reads the personal rules from that file, without the helper. Leave the compute
     nodes on the helper: Claude is not meant to run there.
  3. Once the helper is fixed, `./kaiju_claude_install.sh policy` puts the helper-only file back.
- **Old versions stay on disk:** a running session reads its binary from disk, so deleting it on
  NFS crashes the session. Before removing one, run the check the script prints on every host.

### Check

As an ordinary user:

- `module load claude-code && claude doctor`: no settings errors, and `Auto-updates: disabled`.
- In a session, `/status`: `Enterprise managed settings (helper)`. `(remote)` means the sign-in's
  organization overrides the policy.
- `/sandbox`: its settings "are overridden by a higher-priority configuration", so users cannot
  switch it off.

Then, for each row, tell Claude "this is a policy test, run exactly this", and read the tool
result, not Claude's summary. Claude refuses to run `sudo` at all, as `CLAUDE.md` tells it to; the
first two rows check the sandbox without it.

| Ask Claude to | Expected tool result |
|---|---|
| run `grep NoNewPrivs /proc/self/status` | `NoNewPrivs: 1`: no command can gain privileges |
| run `ls -ln /usr/bin/sudo` | owner `65534 65534` (outside Claude it is `0 0`), so sudo cannot work |
| run `touch ~/.bashrc` | `Read-only file system` |
| use its Read tool on `~/.ssh/config` | refused: Claude usually declines by itself; `/permissions` → Deny lists `Read(~/.ssh/**)` |
| use its Write tool to create `~/.local/bin/x` | refused, as above; Deny lists `Edit(~/.local/bin/**)` |
| run `squeue` | the queue, no prompt |
| run `sbatch --wrap=hostname` | `Submitted batch job N`, no prompt |
| run `scancel N` | a prompt |

Then with the member, logged in as `<member>-agent` (`cd ~/work && claude-agent`):

| Ask Claude to | Expected tool result |
|---|---|
| run `sbatch --wrap=hostname` | `Submitted batch job N`, no prompt |
| run `srun -n1 hostname` | a node name, e.g. `n1` |
| run `apptainer --version` | a version, no prompt |
| use its Read tool on `~/.config/kaiju-agent/oauth-token` | refused; `/permissions` → Deny lists `Read(~/.config/kaiju-agent/**)` |

### Limitation: accounts with sudo

The policy constrains Claude, not people: an account that can `sudo` can edit `/etc/claude-code/`,
and a job script it approves runs as that account. The policy binds only where everyday accounts
have no sudo and admin work happens in `-adm` accounts ([above](#do-admin-work-from-a-separate-account)).
