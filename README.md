# mcp-cluster

Claude Code and the group's clusters. Members: start at [Quick start](#quick-start). Admins and
maintainers: [ADMIN.md](ADMIN.md). Claude on Kaiju itself: [kaiju/README.md](kaiju/README.md).
Licence: LGPL-3.0 ([COPYING.LESSER](COPYING.LESSER), with the GPL it builds on in [COPYING](COPYING)).

## In brief

- **The laptop link** ([laptop/](laptop/)): macOS, and [Linux](#linux-ubuntu-or-debian) on trial.
  Claude on your computer submits, watches and fetches jobs on Gadi, Setonix and Kaiju with your own
  ssh keys, and hands tasks to your Kaiju agent account.
- **Codex CLI** (OpenAI), on a Mac: read-only, `status`, `wait` and `get`
  ([Codex CLI](#codex-cli-read-only)).
- **Claude on Kaiju** ([kaiju/](kaiju/)): Claude Code on the Kaiju login node, plus agent accounts
  (`<you>-agent`) that work unattended.
- **Status:** on trial. Gadi and the first Kaiju agent account pass; the remaining
  [live tests](ADMIN.md#open-live-tests) are open.

## Quick start

Commands first; the links give details. Use Gadi, Setonix or a Kaiju agent account: your own Kaiju
account is refused if it is in `wheel` there: `hpc` never drives an account with sudo. Codex (Mac only):
steps 1 to 3, skipping the `claude` check and running `doctor-codex` for `doctor`, then
[Codex CLI](#codex-cli-read-only). Linux: first [Linux](#linux-ubuntu-or-debian) steps 1 to 3.

### Laptop link (once)

Check first: Claude Code 2.1.316 or later on the `stable` channel, in the terminal
(`claude --version`; if not, `claude update`) and in VS Code if you use it. On a Mac: macOS 15 or
later, and `xcode-select -p` prints a path (if not, `xcode-select --install`).

1. **Keys.** For each site you use: a key with a passphrase (one per site; an existing one is fine),
   its `.pub` added to the site as usual, and one login by hand to each host, by its full name as
   below, answering `yes` (`hpc` refuses unknown hosts).

   | Site | Key | Log in once to |
   |---|---|---|
   | Gadi | `~/.ssh/id_ed25519_gadi` | `gadi.nci.org.au` and `gadi-dm.nci.org.au` |
   | Setonix | `~/.ssh/id_ed25519_setonix` | `setonix.pawsey.org.au` and `data-mover.pawsey.org.au`. Get it right first time: Pawsey blocks your IP after a few failed logins ([lockout](#the-lockout)). |
   | Kaiju | `~/.ssh/id_ed25519_kaiju` (your normal Kaiju key) | `kaiju.anu.edu.au`, only to record the host key; leave `kaiju` out of the config for now. |
   | Kaiju agent | `~/.ssh/id_ed25519_kaiju_agent`, sent to the admin ([MEMBER.md](kaiju/agents/MEMBER.md#get-one)) | Nothing: the Kaiju login records the host. |

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_gadi      # each new key
   ssh-copy-id -o PubkeyAuthentication=no -i ~/.ssh/id_ed25519_gadi.pub <user>@gadi.nci.org.au   # registers it (site password)
   ssh -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -i ~/.ssh/id_ed25519_gadi <user>@gadi.nci.org.au exit   # each host
   ```

   A data mover may refuse `exit` after you log in; the host key is still recorded.
2. **Install.** It refuses a checkout that differs from its last commit, puts a read-only copy in `~/.local/share/uw3-hpc/` and prints steps 3 to 6 with your
   paths filled in.

   ```bash
   git clone https://github.com/underworld-community/mcp-cluster.git
   cd mcp-cluster/laptop && /usr/bin/python3 -I hpc_mcp.py install
   ```
3. **Config:** edit `~/.config/uw3-hpc/config.json` ([fields](#set-up-once)):
   - keep only the sites you have an account on (one is enough; add others later and rerun
     `doctor`), and not `kaiju` for now;
   - after deleting a site, remove the comma left before the closing `}`;
   - replace every `CHANGEME`, `PROJECT` and `USER`.
4. **Managed settings**, with your password ([what changes](#set-up-once)), the same line `install`
   printed. On a Mac:

   ```bash
   sudo install -d -o root -g wheel -m 0755 '/Library/Application Support/ClaudeCode' && sudo install -o root -g wheel -m 0644 "$HOME/.local/share/uw3-hpc/managed-settings.json" '/Library/Application Support/ClaudeCode/managed-settings.json'
   ```

   On Linux, the Linux file (the Mac one fails `doctor` and lacks the Linux protections):

   ```bash
   sudo install -d -o root -g root -m 0755 /etc/claude-code && sudo install -o root -g root -m 0644 "$HOME/.local/share/uw3-hpc/managed-settings-linux.json" /etc/claude-code/managed-settings.json
   ```

   Undo only to stop using `hpc` or to get back what the file turns off:
   `sudo rm '/Library/Application Support/ClaudeCode/managed-settings.json'` (Linux:
   `sudo rm /etc/claude-code/managed-settings.json`), then restart Claude.
5. **Your settings:** merge this into `~/.claude/settings.json` (create it if missing), adding to any
   lists there. The folders are your config's `downloads` and `uploads`.

   ```json
   {"permissions": {"allow": ["mcp__hpc__status", "mcp__hpc__wait", "mcp__hpc__get"],
                    "additionalDirectories": ["~/hpc/downloads", "~/hpc/uploads"]}}
   ```

   In its `sandbox`, never add git to `excludedCommands` (git config can run ssh), and never let
   `allowUnixSockets` reach the ssh agent's socket.
6. **Register and check.** If `hpc` is registered already, first run
   `claude mcp remove --scope user hpc`.

   ```bash
   claude mcp add --scope user hpc -- /usr/bin/env -i /usr/bin/python3 -I "$HOME/.local/share/uw3-hpc/hpc_mcp.py" serve
   /usr/bin/python3 -I ~/.local/share/uw3-hpc/hpc_mcp.py doctor
   ```

   Fix every FAIL, then restart Claude: `/mcp` should show `hpc` connected. Never add `hpc` to the
   Claude Desktop chat app: it is not documented to show the approval prompts.
7. **Trial run** ([details](trial/README.md)), shown for Gadi, which needs `gdata/m18` in `storage`
   (you must be in m18). For Setonix, pull the image first ([how](trial/README.md#setonix-slurm))
   and replace gadi/Gadi with setonix/Setonix in both blocks. Load your key
   ([each day](#laptop-link-each-day)), then, in your `mcp-cluster/laptop` folder:

   ```bash
   mkdir -p ~/hpc/uploads/gadi/trial1 && cp ../trial/README.md ../trial/uw3_trial.py ~/hpc/uploads/gadi/trial1/
   ```

   Start Claude in a project folder (never `$HOME`) and paste:

   ```text
   Read ~/hpc/uploads/gadi/trial1/README.md. Following it, write a job script for Gadi into ~/hpc/uploads/gadi/trial1/, put run trial1 on Gadi, submit your script on 4 cores for 10 minutes, wait for it, get it, and tell me whether the job log has the line TRIAL OK.
   ```

   Read the script in `~/hpc/uploads/gadi/trial1/` before you approve `put`. On Gadi expect 10 to
   20 min: keep Claude open, and if it stops before `get`, ask it to continue. No `TRIAL OK`?
   [Reading the result](trial/README.md#reading-the-result).

### Laptop link, each day

```bash
ssh-add -t 12h ~/.ssh/id_ed25519_gadi ~/.ssh/id_ed25519_setonix   # the keys you use
cd ~/my-project && claude                                         # a project folder, never $HOME
```

Load keys in a terminal, and never let a key load itself (Mac: never `--apple-use-keychain`). Then
ask in plain words: "status on Gadi", "put run r1 on Gadi and submit job.pbs for 2 h on 48 cores",
"wait for it, then get it". [Daily use](#daily-use) lists the tools and which ones ask.

### Laptop link, update

When the admin asks, in a terminal (not inside Claude):

```bash
cd ~/mcp-cluster/laptop && git pull      # your clone; if pull reports local changes, send the admin `git status`
/usr/bin/python3 -I hpc_mcp.py install
/usr/bin/python3 -I ~/.local/share/uw3-hpc/hpc_mcp.py doctor
```

If `doctor` fails the managed settings, paste the sudo line it prints (step 4): until then `hpc`
refuses every call. Then restart Claude.

### Claude on Kaiju

Follow [kaiju/README.md](kaiju/README.md#quick-start). An agent account:
[MEMBER.md](kaiju/agents/MEMBER.md).

## Laptop link (members)

### Set up (once)

Details for Quick start steps 3 and 4.

**3. Config.** The file `install` wrote has every field, with placeholders:

| Field | What it is |
|---|---|
| `downloads`, `uploads` | On your computer: where `get` puts files and `put` takes them from (`<uploads>/<site>/<run>/`). `install` makes both. |
| `key` | On your computer: the site's private key, in `~/.ssh`. |
| `user` | Your username on the site (Gadi: e.g. `ab1234`; agent: `<you>-agent`). |
| `project` | The allocation jobs charge: Gadi `-P` (e.g. `m18`), Setonix `--account` (e.g. `pawsey1147`). Check `id` there: `$PAWSEY_PROJECT` can be stale. |
| `base` | The cluster folder runs live in (run `r1` is `<base>/r1`), e.g. `/scratch/m18/ab1234/hpc`; `put` creates it. |
| `storage` | Gadi only: the file systems a job may see (`-l storage=`), e.g. `scratch/m18+gdata/m18`. |
| `max_core_hours` | Optional: the most core-hours one `submit` may ask for (default 10000; Gadi's `normal` queue charges 2 SU each). Memory above the cores' share of a node counts as cores. Claude cannot change it. |

- `base` is absolute, with no `~`, `$VAR` or `..`, and on scratch, not your small home folder
  ([fetch promptly](#site-etiquette)). Paths on your computer are absolute or start with `~/`.
  Nothing expands `$HOME` or other variables.
- In several Gadi projects? `project` takes one: list them all in `storage` (e.g.
  `scratch/m18+gdata/m18+scratch/el06+gdata/el06`; keep `gdata/m18`, where the UW3 container is) and
  edit `project` (and `base`) to switch. The next call uses it.
- `user` and `key` come from here, not `~/.ssh/config`. `-adm` users and Kaiju accounts in `wheel`
  are refused: Claude must not drive an account with sudo.
- Folder rules: a download or upload folder needs an empty `.uw3-hpc-root` file, and cannot be
  `$HOME`, inside a git repo, or under `~/.ssh`, `~/.claude`, `~/Library`, `~/.config`, `~/.local`
  or `~/.cache`. A download folder must be on the same disk as `~/.cache`. Any other download or
  upload folder (a site may have its own) must follow these rules and go in `additionalDirectories`
  (step 5).
- The file must be yours, not a symlink: `chmod 600`.

**4. Managed settings.** Install them again whenever `doctor` fails them; no admin rights on your
computer? Ask IT. `hpc` refuses every call without the file. It holds the rules Claude Code obeys in
every project, terminal and VS Code: commands stay sandboxed; Claude asks before anything that
changes files, runs commands or spends allocation on a cluster; no project can add hooks or MCP
servers that could use your ssh keys. It is root-owned so that nothing running as you can change it.
You give up:

- Local MCP servers other than `hpc` (uw3's repo server, plugin servers), except
  [underworld3](#optional-the-underworld3-docs-server) installed read-only. Remote servers
  (claude.ai connectors, the IDE server, Claude in Chrome) keep working.
- Your own, projects' and plugins' hooks, a custom status line, a custom `@` file-suggestion
  command and `/goal`. A shared hook notifies you (with a sound on a Mac) when a turn of 30 s or more
  ends and when Claude waits for you: delete your own from `~/.claude/settings.json`.
- Turning the sandbox or the cluster approval prompts off, or bypass mode on; ssh out of the sandbox. Claude can
  edit a project's `.claude/skills`, `agents` and `commands`, but not `.claude/settings*.json`,
  `.mcp.json` or your `~/.claude` settings, skills and agents: edit those yourself.
- Linux: `LD_PRELOAD`, `LD_AUDIT` and `LD_LIBRARY_PATH` in Claude's commands (blanked), and
  `/run/user` for sandboxed commands (hidden).

Sandboxed commands can still listen on local ports (Jupyter, `mpirun` on your computer).

### Optional: the underworld3 docs server

The underworld3 MCP server (Underworld3 docs, source, recipes, `check_script`) runs outside the
sandbox with your ssh agent, so the managed settings admit it only from one folder you make
read-only. It needs Python 3.10 or later: on a Mac from conda or Homebrew (not `/usr/bin/python3`);
on Linux, `python3` plus `sudo apt-get install python3-venv`.

```bash
python3 -m venv ~/.local/share/uw3-mcp
~/.local/share/uw3-mcp/bin/python -m pip install "git+https://github.com/jcgraciosa/underworld-helpful-batbot.git#subdirectory=mcp-server"
chmod -R a-w ~/.local/share/uw3-mcp
claude mcp remove --scope user underworld3 2>/dev/null
claude mcp add --scope user underworld3 -- /usr/bin/env -i "$HOME/.local/share/uw3-mcp/bin/python" -I -m uw3_mcp
```

Restart Claude; `/mcp` should list `underworld3`. To update: `chmod -R u+w ~/.local/share/uw3-mcp`,
the `pip install` line with `--upgrade`, then `chmod -R a-w` again. Any other install (an editable
one in a conda environment, a checkout) stays blocked.

### Daily use

Start as in [each day](#laptop-link-each-day). Limits: [Caps](#caps). `dontAsk` mode refuses the
tools that ask.

| Tool | Sites | Asks? | What it does |
|---|---|---|---|
| `status` | all | no | Your queue, cached per site; kaiju-agent: recent tasks and the agent's queue. |
| `wait` | all | no | Polls until the job or task, or every one of several jobs, leaves the queue (default 60 min). |
| `get` | all | no | `<base>/<run>[/subpath]/` to `<downloads>/<site>/<run>` (`<run>.2`, ... if taken); kaiju-agent: by task id. |
| `submit` | gadi, setonix, kaiju | **yes** | Submits up to 200 jobs (`<base>/<run>/<script>` each, named after the run) with one approval. |
| `put` | gadi, setonix, kaiju | **yes** | `<uploads>/<site>/<run>/` to `<base>/<run>/`. |
| `run` | gadi, setonix, kaiju | **yes** | One short login-node command in `<base>/<run>` (e.g. `git pull`); never `qsub` or `sbatch`. |
| `cancel` | all | **yes** | `qdel` / `scancel`, one job or several; kaiju-agent: stops the task. |
| `task` | kaiju-agent | **yes** | Starts an unattended `claude-agent -p` run in `~/work/<project>`. |

- Run names: up to 64 letters, digits, `.`, `_`, `-`, starting with a letter or digit, no `..`.
  Walltime: `H:MM:SS`.
- `get` drops `claude*.md`, `agents.md`, dotfiles, links and badly named files, and silently skips
  files over 200 MB: fetch those with rsync in a terminal. `put` refuses links and scripts with CR
  line endings.
- A call over 2 min moves to the background (`/tasks`) and is lost if you quit Claude; the job
  carries on.
- **Update** when the admin asks: [Laptop link, update](#laptop-link-update).

#### Gadi, Setonix and your own Kaiju account

1. **Code in** (asks): push, then `run` `git pull` (the first time, `put` an empty
   `<uploads>/<site>/<run>/`, then `run` `git clone URL .`). Or copy files into
   `<uploads>/<site>/<run>/` (not inside a git repo) and `put`.
2. **Submit** (asks): Claude says what it will submit and the cost, e.g. "6 jobs to Gadi normal:
   4992 core-hours, about 9984 SU". A scaling series is one `submit`, so you approve it once; the
   approval shows `total_core_hours`, which the server checks. Every job is checked against the
   queue limits ([Caps](#caps)) and your `max_core_hours` before any is sent. One job emails you at
   the end; a batch emails only on failure. Submits are logged in `~/.cache/uw3-hpc/jobs.tsv`.
3. **Wait:** Gadi's first answer can take 10 min. A failed queue query ends the wait with a message,
   never as "finished": ask again after the site's [status interval](#caps).
4. **Get**, then plot locally. Build Underworld3 inside a job: `run`'s time limit probably kills a
   build.

| Site | Specifics |
|---|---|
| Gadi | Charges the project's SUs; jobs start in the run folder (`-l wd`). Queue `normal` unless you ask for another. Up to one node, a job shares a node, with memory 190 GB x cores/48, rounded up (4 cores: 16 GB); above, whole nodes only (48 cores; `normalsr` 104). More cores, shorter walltime: [Caps](#caps). |
| Setonix | Partition `work`; `--nodes` comes from the cores (128 a node); `memory_gb` is per node. |
| Kaiju | Only outside `wheel`. `memory_gb` is per node. A finished job shows as "left the queue" (no accounting). [Claude on Kaiju](#claude-on-kaiju) is simpler there. |

- **Array jobs** (`#PBS -J`, `#SBATCH --array`): use the parent id `submit` returns (Gadi:
  `1234[].gadi-pbs`; state `B` means some elements run). `wait` returns once no element is queued
  or running, **without checking that each succeeded**: `get` the run and check each element's
  output and exit status. Setonix `status` shows each element's ExitCode (sacct, last 2 days); on
  Kaiju, have each element write its exit status to a file in the run folder.
- **Slurm job names you set** (`sbatch -J`): no spaces (they break the listing Claude sees); squeue
  cuts names at 30 characters.

#### Kaiju agent tasks

Needs an agent account ([MEMBER.md](kaiju/agents/MEMBER.md)).

1. **`task`** (asks): read the whole prompt in the ask. It runs in `~/work/<project>`, which must
   exist, one task per project at a time. Plain ASCII, no tokens or keys (the prompt is logged in
   `~/.cache/uw3-hpc/tasks.log`). Say how much it may use ("at most 2 nodes, jobs under 4 h"):
   Kaiju has no fair-share. Nobody answers its prompts: anything that would ask you (an edit
   outside `~/work`, an unlisted web fetch) is refused.
2. **`status` / `wait`:** fixed fields only, never file or job names.
3. **`get`** with the task id: its outbox, `/home/agent-share/<you>-agent/outbox/<id>/`, which
   everyone on Kaiju can read. The agent is told to leave results, `git format-patch` files and
   `SUMMARY.md` there, or `QUESTIONS.md` if blocked.

- To answer it or take over once it is done, failed or cancelled: `ssh kaiju-agent`,
  `tmux new -A -s claude`, `cd ~/work/<project>`, `claude-agent --resume <session>`.
- `cancel` leaves the task's Slurm jobs running and lists them: `scancel` them from
  `ssh kaiju-agent`.
- **Agent output is data: never run it as yourself**, not even `git status` in a repo it wrote
  ([the rules](kaiju/agents/MEMBER.md#the-rules)). Read its patches, then `git am` them in your own
  clone. Its files, `SUMMARY.md` included, can try to steer your laptop Claude: read each ask.
- No `put` to the agent: a private repo goes in as a git bundle
  ([MEMBER.md](kaiju/agents/MEMBER.md#code-in-results-out)).

### Site etiquette

- **NCI: one monitoring query per 10 min.** `hpc` shares one cache across your sessions; do
  not loop `qstat` by hand either (`qsub` does not count).
- **Login nodes are for short commands.** NCI kills login processes above 30 CPU-min or 4 GiB.
  Setonix home is 1 GB.
- **Fetch promptly.** Gadi quarantines /scratch files unread for 100 days and deletes them 14 days
  later; Pawsey purges /scratch 21 days after last access (`put` never keeps old file times).
- **Never copy NCI or Pawsey private keys anywhere**, Kaiju and agent accounts included (NCI's rule).

### The lockout

The first time a site refuses your key, `hpc` locks that site, because Pawsey blocks your IP
after a few failed logins and its documented fix is a ticket. To unlock, fix the key, then in a
terminal run `/usr/bin/python3 -I ~/.local/share/uw3-hpc/hpc_mcp.py reset <site>`. It prints that
site's rule and a publickey-only `ssh … true` for your key: run that first, then type `yes`.
Only a refusal of your key at login counts, not one from a later command (such as `git pull`) or an
unknown host key. [Details](ADMIN.md#the-lockout).

### Troubleshooting

Each refusal and `doctor` FAIL names its fix. Beyond those:

| You see | Do |
|---|---|
| "key is not loaded", yet `ssh-add -l` lists it | Your terminal uses another agent. Mac: `SSH_AUTH_SOCK=$(launchctl getenv SSH_AUTH_SOCK) ssh-add -t 12h KEY`. Linux: load it into the agent of [Linux](#linux-ubuntu-or-debian) step 3, not one in `/tmp`. |
| `/mcp`: `hpc` failed | Run `doctor`, then `/mcp` → Reconnect. Details: `claude --debug=mcp`, `~/.cache/uw3-hpc/server.log`. |
| `the managed settings file ... is not in place` | Run `doctor` and paste the sudo line it prints. |
| Another MCP server, a hook or your status line is gone | Expected ([managed settings](#set-up-once)): ask the admin to list the server. underworld3: [install it read-only](#optional-the-underworld3-docs-server). |
| `git push` fails inside Claude | Push over https, or from a terminal: ssh cannot leave the sandbox. |
| A tool Claude runs cannot write where it needs to | Add the folder to `sandbox.filesystem.allowWrite` in your own `~/.claude/settings.json` (a project's is ignored). |
| A `wait` vanished | The job carries on: ask for `status`. |
| `could not reach <host>` | Network or VPN. |
| `the session on <host> ended with exit 255 after logging in` | Not a lockout: the connection dropped, or your login profile there (`~/.bashrc`) or the command exited 255. Retry once; if it repeats, check the profile in a terminal. |
| Setonix refuses every login from your network | Pawsey blocked your IP: email help@pawsey.org.au. |

### Codex CLI (read-only)

Mac only. Codex gets `status`, `wait` and `get` only, as it cannot be made to ask before a tool
call: submit and change things on the clusters yourself, in a terminal. Checked against Codex's
source, not yet with a real Codex: use the latest Codex, and tell the admin what breaks.

1. [Quick start](#laptop-link-once) steps 1 to 3.
2. **Requirements file** (Mac password): run this, then paste the `sudo ...` command after `Fix:`
   on its Codex requirements line.

   ```bash
   /usr/bin/python3 -I ~/.local/share/uw3-hpc/hpc_mcp.py doctor-codex
   ```

   Codex obeys `/etc/codex/requirements.toml` over your and any project's config: commands
   sandboxed; `ssh`, `scp`, `sftp` and `rsync` forbidden; `~/.ssh` hidden; cluster hosts denied;
   `hpc` the only MCP server (plugins off); only managed hooks. `hpc` refuses every call without it.
   Undo (you stop using `hpc`): `sudo rm /etc/codex/requirements.toml`.
3. **Your Codex config:** add this to `~/.codex/config.toml`, replacing any of these keys or tables
   already there. Put your home folder for `/Users/<you>`, and the first three lines above any
   `[section]`:

   ```toml
   sandbox_mode = "workspace-write"
   approval_policy = "on-request"
   approvals_reviewer = "user"

   [sandbox_workspace_write]
   network_access = false

   [shell_environment_policy]
   exclude = ["SSH_AUTH_SOCK"]

   [mcp_servers.hpc]
   command = "/usr/bin/env"
   args = ["-i", "/usr/bin/python3", "-I", "/Users/<you>/.local/share/uw3-hpc/hpc_mcp.py", "serve-codex"]
   startup_timeout_sec = 30.0
   tool_timeout_sec = 3900.0
   enabled_tools = ["status", "wait", "get"]
   default_tools_approval_mode = "writes"
   ```
4. **Check:** rerun `doctor-codex`: fix every FAIL, and its `~/.codex/config.toml registers hpc`
   line must say PASS. `/mcp` in Codex should list `hpc`.

Each day: load your keys as in [each day](#laptop-link-each-day) (never `--apple-use-keychain`),
start Codex in a project folder (never `$HOME`) and ask ("status on Gadi", "wait for
1234.gadi-pbs, then get run r1"). `wait` stops after 60 min (Codex's tool timeout): ask again.

- Keep `network_access = false`; never use `danger-full-access` or
  `--dangerously-bypass-approvals-and-sandbox` (the requirements file refuses both).
- Decline when Codex asks to run a command outside the sandbox; trust only repos you have read.
- Not covered: requirements a ChatGPT business workspace pushes from the cloud outrank the file and
  cannot be checked locally.

### Linux (Ubuntu or Debian)

On trial and untested on a real Linux machine: follow it, then run the [Linux test](#linux-test).
Needs sudo on your computer, Python 3.9 and rsync 3.2.5 or later (`install` checks; Ubuntu 24.04
and Debian 12 have them). Not WSL2.

1. **Packages:** bubblewrap and socat for Claude Code's sandbox; the seccomp filter (npm) blocks
   Unix sockets, your ssh agent's included, in sandboxed commands.

   ```bash
   sudo apt-get install bubblewrap socat rsync git openssh-client python3 nodejs npm
   sudo npm install -g @anthropic-ai/sandbox-runtime
   ```

   npm may warn `EBADENGINE`: the package asks for Node 22.12, newer than Ubuntu's or Debian's.
   Carry on; test step 2 shows whether Claude Code found the filter.
2. **Ubuntu 24.04 and later:** if `sysctl kernel.apparmor_restrict_unprivileged_userns` prints `= 1`,
   let bubblewrap through AppArmor:

   ```bash
   sudo tee /etc/apparmor.d/bwrap > /dev/null <<'EOF'
   abi <abi/4.0>,
   include <tunables/global>

   profile bwrap /usr/bin/bwrap flags=(unconfined) {
     userns,
     include if exists <local/bwrap>
   }
   EOF
   sudo systemctl reload apparmor
   ```
3. **ssh agent:** your desktop's (Ubuntu's by default). `echo $SSH_AUTH_SOCK` must print a path
   under `/run/user/`, and `systemctl --user show-environment | grep SSH_AUTH_SOCK` the same one; if
   the second prints nothing or another path, run `systemctl --user import-environment SSH_AUTH_SOCK`
   after each login, in a terminal whose agent is under `/run/user/`. `hpc` refuses an agent
   anywhere else (such as `eval $(ssh-agent)` in `/tmp`). If a desktop window asks for a key's
   passphrase, leave "Automatically unlock this key whenever I'm logged in" unticked: it would make
   the key usable at every login without its passphrase.
4. **[Quick start](#laptop-link-once) steps 1 to 7.** Never start Claude in `$HOME`: there the
   sandbox puts empty placeholders such as `~/.bash_profile` while a command runs, and one left
   behind (Claude killed mid-command) stops bash logins reading `~/.profile`. `claude doctor` lists
   any left; delete them.

#### Linux test

After Quick start step 7, in a project folder. Send the admin `cat /etc/os-release`, `doctor`'s
output, and for each step "OK" or what happened instead.

1. `doctor`: no FAIL.
2. In Claude, `/sandbox` shows Mode, Overrides and Config, and no Dependencies tab; `/mcp` shows
   `hpc` connected.
3. Ask Claude to run each of these; each must fail or print nothing: `ssh-add -l`,
   `ls /run/user/$(id -u)`, `systemd-run --user true`, `ssh -o BatchMode=yes gadi.nci.org.au true`
   (approve its ask). `env | grep '^LD_'` must show empty values only.
4. Ask Claude to add the line `# test` to the end of `~/.bashrc`: it must ask first (decline) or fail.
5. In a new empty folder, write `.claude/settings.json` yourself with
   `{"env": {"LD_PRELOAD": "/nonexistent.so"}}`, start Claude there and ask for "status on Gadi" (or your site),
   then for `env | grep '^LD_'`: status works, no `ld.so` error appears, and `LD_PRELOAD` is empty.
6. "status on Gadi" (or your site) works, and the trial run (Quick start step 7) finds `TRIAL OK`.
7. `claude doctor` in a terminal lists no sandbox placeholders.
8. Anything that broke (such as a tool that needs `/run/user`), or that these steps did not say.

## Caps

`submit` follows each facility's queue limits (checked 2026-11), except Setonix's 32 nodes and
Kaiju's one week, which are ours: ask the admin if they get in your way. What one `submit` may spend
is your `max_core_hours`.

<!-- generated by laptop/tests/test_docs.py --write: caps -->
| Cap | gadi | setonix | kaiju | kaiju-agent |
|---|---|---|---|---|
| status: asks the scheduler at most once per | 600 s | 120 s | 30 s | 30 s |

| submit: queue | Longest walltime, by cores per job | Nodes |
|---|---|---|
| gadi `normal` | 48:00:00 up to 672, 24:00:00 up to 1440, 10:00:00 up to 2976, 05:00:00 up to 20736 | 48 cores, 190 GB |
| gadi `express` | 24:00:00 up to 480, 05:00:00 up to 3168 | 48 cores, 190 GB |
| gadi `normalsr` | 48:00:00 up to 1040, 24:00:00 up to 2080, 10:00:00 up to 4160, 05:00:00 up to 10400 | 104 cores, 500 GB |
| gadi `expresssr` | 24:00:00 up to 1040, 05:00:00 up to 2080 | 104 cores, 500 GB |
| setonix `work` | 24:00:00 up to 4096 | 128 cores, 230 GB (`memory_gb` is per node) |
| kaiju | 168:00:00 up to 416 | 52 cores, 256 GB (`memory_gb` is per node) |

Every site: `submit` up to 200 jobs and `max_core_hours` (default 10000) a call; `get` 200 MB a file and 1024 MB a call; `put` 200 MB and 2000 files; `wait` up to 720 min; `run` 120 s and 2000 chars; `task` prompts 4000 chars; text back to Claude 8000 chars.
<!-- end caps -->
