# mcp-cluster: admin

For the admin and maintainers: how the laptop link and Claude on Kaiju are built, secured, tested
and kept up. Members: [README.md](README.md).

## How it fits together

```text
Your computer                                     Clusters
Claude Code (terminal or VS Code)
  |  Bash: sandboxed, cluster hosts denied
  |  mcp__hpc__* tools, over stdio
  v
hpc MCP server ---- ssh/rsync, your keys ---+--> Gadi     PBS    gadi, gadi-dm
  (laptop/, runs as you: asks,              +--> Setonix  Slurm  setonix, data-mover
   caps, lockout, cleans replies)           +--> Kaiju    Slurm  your account
                                            +--> Kaiju    agent  <you>-agent account
managed-settings.json (root-owned)                  `-- claude-agent -p runs each task,
  fences Claude on the Mac                              results in its outbox

On Kaiju itself (kaiju/): members run `claude`, agent accounts `claude-agent`,
both under the policy in /etc/claude-code.
```

## Claude on Kaiju

| Read | For |
|---|---|
| [kaiju/README.md](kaiju/README.md) | install, update, checks |
| [kaiju/agents/README.md](kaiju/agents/README.md) | create, suspend and audit agent accounts |
| [kaiju/agents/CHECKS.md](kaiju/agents/CHECKS.md) | go/no-go for the first agent account |

- `/etc/claude-code/managed-settings.json` on every node names only `policy-helper`, which picks
  `policies/human.json` or `policies/agent.json` from the caller's uid and groups and refuses root,
  `-adm` and half-made agent accounts. If the helper fails, Claude does not start.
- The installer pushes the policy to every node before it installs a binary.
- Signing in to a Team or Enterprise organization that sets Claude Code settings in claude.ai
  replaces the whole policy and skips the helper [managed; setref]. `/status` must show
  `Enterprise managed settings (helper)`; the member docs say so.
- For an account that can `sudo`, the policy constrains Claude, not the person
  ([details](kaiju/README.md#limitation-accounts-with-sudo)).

## Security

### The managed settings file

What members gain and give up: [Set up, step 4](README.md#set-up-once). Each key of
[laptop/managed-settings.json](laptop/managed-settings.json), and those only
[the Linux file](laptop/managed-settings-linux.json) adds:

| Managed key | Why |
|---|---|
| `allowManagedHooksOnly`, `hooks` | Hooks run outside the sandbox with the ssh agent, so only managed ones run. Ours runs the installed, read-only `notify.sh` with absolute paths only (a project's `env` reaches hooks) and prints nothing (`UserPromptSubmit` output reaches Claude). |
| `allowManagedMcpServersOnly`, `allowedMcpServers` | Only this list counts. `hpc` and underworld3 match their exact commands; with a `serverCommand` entry present, every stdio server must match one, so a repo cannot pass a server off as `hpc`. Underworld3 runs from `~/.local/share/uw3-mcp`, which Claude cannot edit and the member makes read-only. `https://*/*` admits every remote server (claude.ai connectors each have their own provider's URL): they run elsewhere and never see the ssh agent. |
| `disabledMcpjsonServers: ["hpc", "underworld3"]` | A repo's `.mcp.json` entry with either name can never be approved (backstop) [mcp:272,795]. |
| `permissions.disableBypassPermissionsMode` | No `--dangerously-skip-permissions`. |
| `permissions.ask` | The five acting tools, raw `ssh`, `scp`, `sftp`, `rsync`, and edits to startup files (decision 12). Ask beats allow from any scope. |
| `sandbox.filesystem.denyWrite` | The same startup files, for sandboxed commands when Claude starts in `$HOME` (decision 12). |
| `permissions.deny` | [Protected paths](#protected-paths) [modes:30]. |
| `sandbox.enabled`, `failIfUnavailable`, `allowUnsandboxedCommands: false` | Always sandboxed, no unsandboxed retry. The sandbox becomes admin-required, so a repo's `excludedCommands`, `allowedDomains`, `allowUnixSockets` and proxy ports are ignored. |
| `sandbox.filesystem.denyRead: ~/.ssh` | The sandbox can read `~/.ssh` by default. |
| `sandbox.network.allowAllUnixSockets: false` | A managed Boolean sandbox key overrides the member's, so a user-level `true` cannot expose the agent socket [setref]. |
| `sandbox.network.allowLocalBinding: true` | Jupyter and `mpirun` on the laptop: a listener on localhost gives no way out to a cluster. |
| `sandbox.network.deniedDomains` | Every login and data-mover node by name (`*.nci.org.au`, `*.pawsey.org.au`) and Kaiju's IP, in every mode [sbx:582,611]. |
| Linux only: `env` blanks `LD_PRELOAD`, `LD_AUDIT`, `LD_LIBRARY_PATH` | A project could use them to run code as the member outside the sandbox. |
| Linux only: `sandbox.filesystem.denyRead: /run/user` | Hides the ssh agent's socket, which `hpc` requires there, from sandboxed commands. |
| Linux only: `bwrapPath`, `socatPath`, `enableWeakerNestedSandbox: false`, `allowNestedUserNamespaces: false` | Bubblewrap and socat from `/usr/bin`, not the first on `PATH` (which could be a planted `~/.local/bin` copy) [sbx 2026-11-12]; no weaker or nested sandbox. |

`doctor` fails, and the server refuses every call, unless the file is root-owned, readable by all
and exactly the committed one. An extra key fails (a hook, status line or server it adds would run
with the ssh agent), and so do `*.json` files in `managed-settings.d`, which Claude Code merges over
the file [managed].

### The lockout

Pawsey blocks an IP after a few failed logins and its documented fix is a ticket, so a site's first
refusal of a key locks that site until the member fixes the key and runs `reset`
([README.md](README.md#the-lockout)).

A cluster account cannot fake a refusal. ssh writes `Authenticated to <host>` on login, before the
cluster can send anything, and the cluster can add text after that line but never remove it. A
refusal counts only when that line is missing, so a fake "Permission denied" (say, from an agent
account's `~/.bashrc`) cannot lock anyone out; nor can a remote command's own refusal
(`git@github.com: Permission denied` from `git pull`) or an unknown host key. The only text before
that line that is not ssh's own is the facility's login banner, which the lockout trusts: a banner
holding that line would hide a real refusal, and only the facility's root can set one.

Tested offline and against a real sshd on a Mac, banner included; the Kaiju test is
[open test 10](#open-live-tests).

### Security model (admin)

- **The uid is the boundary.** The server runs unsandboxed as the member with their loaded keys
  [sbx:11,43]; an approved call can do whatever that account can. On Kaiju, delegation goes to the
  agent uid (no sudo); `-adm` and `wheel` accounts are refused.
- **The forced asks** (`_meta` `anthropic/requiresUserInteraction`) cover every call that spends
  SUs, changes remote files, runs a remote command, stops work or instructs the agent. They prompt
  in acceptEdits, auto and bypass, with no "don't ask again" [mcp:1602-1606; modes:38; CL 2.1.246].
  Unprompted tools only read a cached listing, or fetch into a checked folder under checked names,
  placing the result through folder descriptors that never follow a link.
- **They hold only because the raw routes are closed:** by the managed settings (above), which the
  server requires; by `env -i` and `python3 -I` with a fixed child env, against a project's `env`
  (`/usr/bin/python3` is Apple's xcrun shim, which runs whatever `DEVELOPER_DIR` names); and by no
  child on the server's stdout (remote bytes could forge JSON-RPC).
- **The lockout:**
  - ssh runs with `LogLevel=VERBOSE`, the only level that prints `Authenticated to`, and
    `UpdateHostKeys=no`, so no server rewrites `~/.ssh/known_hosts`.
  - A lock needs all three: no `Authenticated to <host> (` naming the exact host (anywhere, as a
    banner without a final newline runs into it), exit 12 or 255, and
    `<user>@<host>: Permission denied (`. The lock file keeps fixed words only.
  - ssh's own VERBOSE lines (transfer counts, the post-quantum warning) and everything before the
    login line (the banner) are dropped before Claude or a log sees stderr.
  - Exit 255 after a login is still refused, so `wait` never reads a dropped connection as
    "finished".
  - Until a login to a site has worked in a session, logins to it go one at a time, each checking
    the lock first.

**Residual risks:**

- An approved `run` is a shell as the member on any site, with no policy on the cluster.
- Downloads can steer laptop Claude. Cluster text is marked untrusted and capped, kaiju-agent
  returns fixed fields only (its project names are its own, up to 64 safe characters), and the
  asks are the backstop.
- A trusted repo's `.claude/settings.json` or `.claude/settings.local.json` can add hooks, `env`,
  MCP servers, proxy ports, Unix sockets and `excludedCommands` [sbx:751-764; setref:2138-2160].
  The managed settings block or ignore all but `env` (hence `env -i`). Still open:
  - its helper commands such as `apiKeyHelper` run outside the sandbox: in any session once the
    repo is trusted, and in `-p` runs or when only a parent folder is trusted [setref; sbx];
  - plugins it enables can bring LSP servers; `strictKnownMarketplaces` would close that (inf), at
    more cost to members.
- A member who is an administrator on their Mac can change the file, and the code that checks it.
  A claude.ai Team or Enterprise org with server-managed policy outranks it, leaving only the
  cross-source keys; `/status` should show "Enterprise managed settings (file)" [managed].
- The allowlist names `hpc` by `${HOME}/.local/share/uw3-hpc/hpc_mcp.py`, so it depends on the
  `HOME` Claude Code starts with. A repo cannot set it; `doctor` warns on a mismatch.
- A Gadi or Setonix IP address, or a name outside the denied domains, is not blocked: it asks in
  Manual mode and goes to the classifier in auto mode [sbx:600-631] ([decision 8](#decisions)).
  The sandbox keeps the ssh agent out, so such a login has no key, but Pawsey may still count it as
  a failure.
- Raw `ssh`/`scp`/`rsync` ask rules keep their matching gaps [perm:250-256]; the sandbox blocks
  them.
- The agent controls its shell rc files, so its rsync sender is hostile input (inf).
- Approval fatigue on submit, eased by batches ([decision 15](#decisions)). `run` refuses `qsub`,
  `qalter`, `qmove`, `qrls`, `qrerun`, `qhold`, `sbatch`, `salloc`, `srun` and `scontrol` (bar `show`) at
  the start of a command, by name only: a script it runs can still submit.

### Protected paths

Generated from [laptop/managed-settings.json](laptop/managed-settings.json) plus `SETTINGS` in
`admin.py` (Laptop), [kaiju/policies/human.json](kaiju/policies/human.json) (Kaiju member) and
[kaiju/policies/agent.json](kaiju/policies/agent.json) (Kaiju agent).

<!-- generated by laptop/tests/test_docs.py --write: protected paths -->
| Path | Laptop | Kaiju member | Kaiju agent |
|---|---|---|---|
| `~/.ssh` | read + edit denied | read + edit denied | read + edit denied |
| `~/.local/share/uw3-hpc`, `~/.config/uw3-hpc`, `~/.local/share/uw3-mcp`, `~/.claude.json`, `~/.claude/skills`, `~/.claude/agents` | edit denied |  | edit denied |
| `~/.cache/uw3-hpc`, `~/.claude/settings*.json`, `**/.claude/settings*.json`, `**/.claude/launch.json`, `**/.claude/hooks`, `**/.mcp.json` | edit denied |  |  |
| `~/.claude/plugins` | edit denied |  | sandbox write-denied |
| `~/.zshrc`, `~/.zprofile`, `~/.zshenv`, `~/.bashrc`, `~/.bash_profile`, `~/.bash_login`, `~/.bash_logout`, `~/.bash_aliases`, `~/.profile`, `~/.tmux.conf`, `~/.gitconfig`, `~/.bashrc.d`, `~/.config/git`, `~/bin`, `~/.local/bin` | edit asks, sandbox write-denied | edit denied | edit denied |
| `~/.zlogin`, `~/.zlogout`, `~/Library/LaunchAgents` | edit asks, sandbox write-denied |  |  |
| `~/.config/autostart` | edit asks |  | edit denied |
| `~/.config/systemd` | edit asks | edit denied | edit denied |
| `~/.gnupg` |  | read + edit denied | read + edit denied |
| `~/.aws`, `~/.netrc`, `~/.git-credentials`, `~/.pypirc`, `~/.docker` |  | read denied | read denied |
| `~/.config/gh`, `~/.apptainer` |  | read denied | read + edit denied |
| `~/.local/lib`, `~/.modulerc`, `/opt/cluster` |  | edit denied | edit denied |
| `~/.claude/settings.json` | edit denied | edit denied | edit denied |
| `~/.claude/.credentials.json` |  |  | read denied |
| `~/.config/kaiju-agent` |  |  | read + edit denied |
| `~/.local`, `~/.config`, `~/.claude/CLAUDE.md`, `~/.claude/commands` |  |  | edit denied |
<!-- end protected paths -->

- **read denied**, **edit denied**: Claude's Read, or Edit and Write, tools are refused, and so are
  its sandboxed commands: Claude Code merges these rules into the sandbox.
- **sandbox write-denied**: only sandboxed commands are refused; Claude's Edit tool asks as usual.
- **Blank**: no rule names the path. Claude's Edit tool still asks outside the project (the agent:
  outside the project and `~/work`), and sandboxed commands write only in the project, temp and the
  listed extra folders.
- A row lists every path with the same protection in all three columns. A broader rule counts (the
  agent's `~/.config` covers `~/.config/gh`). `**/` means anywhere under the folder Claude starts in.
- None of this binds what runs outside the sandbox: the laptop MCP server, and on Kaiju `sbatch`,
  `srun`, `apptainer` and their jobs.

**Every site:**

- `put` writes only under `<base>/<run>`, from a private copy checked file by file.
- `get` never brings back `claude*.md`, `agents.md` or badly named files (a folder goes with
  everything in it; the result counts them), nor links, special files, dotfiles such as
  `.mcp.json`, or files over 200 MB (never sent, so not counted).
- Folder rules for download and upload folders: [README.md, Set up step 3](README.md#set-up-once).
  A download folder must share `~/.cache`'s disk because downloads are moved, never copied, into
  place.

Claude does not run on Gadi or Setonix, so there the laptop server is the limit.

## Decisions

| # | Decision | Answer |
|---|---|---|
| 1 | Build order | Gadi and Setonix first (biggest gain, no Kaiju risk); Kaiju own account only after the `wheel` trim and the `human.json` ask change. `task` is in v1, with no separate profile. |
| 2 | Install location | `~/.local/share/uw3-hpc/`, read-only, no sudo; the managed settings deny Claude edits to it. |
| 3 | Agent results | `get` with the agent key; the MEMBER.md rsync line is a fallback with the same excludes. Never through the human account: the agent owns the outbox, so `outbox/<run>` can be a symlink into the member's home, and rsync follows it (tested with openrsync). |
| 4 | Platform | macOS; Linux (Ubuntu, Debian) on trial from 2026-11-09 with its own managed file, tested on the member's machine ([Linux](README.md#linux-ubuntu-or-debian)). Not WSL2 (its `/etc/claude-code` can be changed from Windows) or RHEL 8 (Python 3.6). |
| 5 | Managed settings | **Settled 2026-11-09:** required on every member's Mac (sudo once), accepting the lost hooks and unlisted MCP servers. The server refuses every call without it. |
| 6 | Preconditions | Separate keys for the everyday and `-adm` accounts. One key per site, each with a passphrase. Settle the `KEY_FROM` promise ([MEMBER.md](kaiju/agents/MEMBER.md#get-one) offers to limit the key to where the member connects from; `KEY_FROM` in `kaiju-agent` ends `,*`). |
| 7 | Fixes still open | `human.json` still allows `sbatch`, `srun`, `apptainer` (the `claude-code` module help says so: change both together). `human.json` lacks `"allowManagedMcpServersOnly": true, "allowedMcpServers": []`, so a trusted repo on Kaiju can add an unsandboxed MCP server. No `.gitattributes`. In uw3-hpc-install-run: `gadi/baremetal/gadi_pbs_job.sh:35` overrides `qsub -v SCRIPT=`; job templates lack `#PBS -j oe`/`-m ae` and `--mail-type=END,FAIL` (the server passes them itself). |
| 8 | Network allowlist | Whether to add `sandbox.network.strictAllowlist: true` (user settings; a repo cannot undo it), with `allowedDomains` for GitHub, PyPI and conda. It closes the IP and other-name gap, but every host Claude's commands use must be listed. |
| 9 | Layout | **Settled 2026-11-09:** this repository, with the `uw3hpc` package and offline tests. Open: where to publish each release's sha256 so `doctor` can compare it. |
| 10 | Caps | **Settled 2026-11-09, for a trial; submit limits replaced 2026-11-12** by decision 15 ([Caps](README.md#caps)). Gadi's 600 s is NCI's rule [NCI]; Pawsey documents no limit, so Setonix's 120 s is unverified. Open: whether `get` stays unprompted on human sites. |
| 11 | Lockout | **Settled 2026-11-09:** a refusal counts only before ssh's login line ([why](#the-lockout)); Kaiju test pending. |
| 12 | Startup files | **Settled 2026-11-12:** both managed files ask before Claude edits shell startup files (zsh, bash, `~/.profile`, `~/.bashrc.d/`), `~/.tmux.conf`, git config, `~/bin`, `~/.local/bin` and login items (`~/Library/LaunchAgents`; Linux `~/.config/autostart`, `~/.config/systemd`), and the sandbox write-denies them, which matters when Claude starts in `$HOME`. They run outside the sandbox with the ssh agent loaded; an ask rule beats any allow and auto mode. Each file lists only its own system's login items: on Linux the sandbox puts a placeholder at a missing denied path while a command runs, but only inside a writable folder, i.e. when Claude starts in `$HOME` [sbx 2026-11-12; srt]. Members rerun the sudo line. |
| 13 | Codex CLI | **Settled 2026-11-09:** read-only (`serve-codex`: `status`, `wait`, `get`), fenced by a root-owned `/etc/codex/requirements.toml` that `serve-codex` checks byte for byte. Checked against Codex's source (openai/codex `8703d32`), not yet with a real Codex. Mac only: `codex_sudo_line` uses group `wheel` and `CODEX_OVER` lists only Mac paths. Open: whether the network proxy starts when `network_access = false`; the first Codex release members need. |
| 14 | Relaxations | **Settled 2026-11-11, low risk:** local ports for sandboxed commands; every remote MCP server (claude.ai connectors); edits to a project's `.claude` skills, agents and commands; one shared notification hook. **With a precaution:** underworld3 from a read-only `~/.local/share/uw3-mcp`. Still blocked: unsandboxed commands, Unix sockets, bypass mode, `~/.ssh`, cluster hosts. |
| 15 | Submit batches | **Settled 2026-11-12:** one `submit` takes up to 200 jobs with one approval (scaling series of up to ~100 jobs, weak scaling to 1000+ cores). The whole batch is checked first against the facility's queue limits (NCI Queue Limits; Setonix `work` 24 h; our 32 Setonix nodes and one Kaiju week) and the member's `max_core_hours` (default 10000 per call, config only). `total_core_hours` (memory above the cores' share counts as cores) is a required argument the server checks, so the approval shows the cost; Claude states the cost (Gadi SU) before each prompted call, and each call's first progress line says what it does. Sent 20 per login with a marker per job, stopping at the first refusal; ids already in are always reported, and a job whose fate is unclear is "may have been submitted", never "not sent". Batches mail only on failure. `wait` and `cancel` take `ids`. `run` refuses job-control commands. |

## Open live tests

1. macOS openrsync (protocol 29) against gadi-dm, data-mover and Kaiju, including a hostile
   agent-side sender (if that fails, `get` switches to `ssh cat` per file). `put` makes the run
   folder over the login host, so gadi-dm needs only rsync.
2. `bash -lc` finds `qsub`, `sbatch` and `module` over ssh: probably on Gadi (inf); Setonix
   untested. Setonix takes `--nodes` over a template's `#SBATCH --nodes=1`.
3. Gadi PBS: `qstat -x -w -u` exits 0 when there are no jobs (otherwise every query reads as
   failed); how long `qstat -x` keeps history; `-l wd`; whether the 10 login nodes share one host
   key (all unverified).
4. Job-end email reaches members from Kaiju, Gadi and Setonix (NCI documents no `-m`/`-M`
   behaviour).
5. **Passed 2026-11-16** (agent canary): `get` fetched a task's outbox with rsync and the agent
   key through the agent Match block, which has no ForceCommand.
6. **Passed 2026-11-16, except `--resume`:** a laptop `task` ran `claude-agent -p --session-id` with
   the setup token, wrote to the outbox through `--add-dir`, kept running after the starting ssh
   ended, and `wait` and `get` followed it (Kaiju, 2.1.316). Still untested: `--resume`.
7. A UW3 build fits in `run`'s 120 s and Gadi's 30 CPU-min or 4 GiB login limit [NCI], or it moves
   into the job.
8. A backgrounded `wait` runs alongside `status`, progress keeps it past 30 min, stop or Esc kills
   the ssh child, and two sessions keep Gadi to one query per 600 s.
9. With the sandbox on, `ssh`, `/usr/bin/ssh` and a `ProxyCommand` through the proxy fail to reach
   each cluster in Manual and auto modes (also `setonix-NN`, an IP address, and the data movers),
   while the server connects and plotting works.
10. The lockout on Kaiju: a refusal printed after a real login does not lock, a real refusal does,
    and `reset` clears it. Then on kaiju-agent, with the fake refusal in the agent's `~/.bashrc`.
11. The managed settings on a member's Mac, in the terminal and VS Code: `/status` shows
    "Enterprise managed settings (file)", `hpc` connects, an unlisted MCP server and a project hook
    are blocked.
12. On Kaiju, an agent session gets `CLAUDE-agent.md` (the `claudeMd` key inside the helper's
    `managedSettings`) alongside `/etc/claude-code/CLAUDE.md` ([CHECKS.md](kaiju/agents/CHECKS.md)
    section 3, the outbox row).
13. Codex on the Codex member's Mac: Codex starts with the requirements file; `/mcp` shows `hpc`
    and no other server; `ssh`, `SSH` and `nc -z` to gadi.nci.org.au fail from its shell with
    `network_access` false and true; `cat ~/.ssh/config` is refused; `status`, `wait` and `get` work
    and `submit` does not exist; ordinary web access behaves sensibly under the network proxy.
14. Linux on the Linux member's machine: the [Linux test](README.md#linux-test).

**The live kit** ([laptop/tests/live/kaiju_live.py](laptop/tests/live/kaiju_live.py)) runs part of
1, 2, 4 and 8, and the own-account half of 10, on your own Kaiju account through this checkout's
server. It asks y/N before each step that reaches Kaiju and needs the managed settings file in
place. While your Kaiju account is in `wheel`, step b is refused by design and c is skipped; d
still works (a one-shot line you add to your Kaiju `~/.bashrc` meets the wheel check's own login).

```bash
cd mcp-cluster/laptop
/usr/bin/python3 -I tests/live/kaiju_live.py --dry-run   # every step and tool call; connects to nothing
ssh-add -t 12h ~/.ssh/id_ed25519_kaiju
/usr/bin/python3 -I tests/live/kaiju_live.py             # --steps abcde, --config PATH, --results FILE
```

Results go to `tests/live/results/kaiju-<time>.json` (git-ignored). Step e uses a throwaway key in
a temp ssh-agent and a temp `--home`, so your real lock state is untouched. Part 2, for kaiju-agent
(tests 5, 6 and the agent half of 10), is only sketched in the kit's docstring.

## Facility contacts

Email help@nci.org.au and help@pawsey.org.au:

- Describe rate-limited laptop submit with each member's own key, and ask about any automation
  rules.
- Ask about MFA plans (none found for either, unverified; MFA would need a login step).
- Ask Pawsey whether a failed-login IP block expires on its own.

## File layout

`->` is where a file is installed.

<!-- file layout: checked by laptop/tests/test_docs.py -->
```text
README.md                    members' guide: the one to read
ADMIN.md                     this file: admin and maintainers
.gitignore                   .DS_Store, __pycache__, Claude Code's .claude/.cc-writes
COPYING                      the GPL-3.0 text, which the LGPL builds on
COPYING.LESSER               the licence: LGPL-3.0
laptop/                      the laptop link: Python 3.9 standard library only, macOS and Linux
  .gitignore                 __pycache__, the live kit's results
  hpc_mcp.py                 entry point: serve, serve-codex, install, doctor, doctor-codex, reset, selftest
  managed-settings.json      the Mac's Claude Code policy -> /Library/Application Support/ClaudeCode/
  managed-settings-linux.json  the same for Linux, plus its keys -> /etc/claude-code/
  codex-requirements.toml    Codex's policy for serve-codex, filled in per member -> /etc/codex/requirements.toml
  uw3hpc/                    the server package; install copies it read-only to ~/.local/share/uw3-hpc
    __init__.py              the version
    sites.py                 what an admin edits: sites, hosts, caps, floors, name and id patterns
    util.py                  refusals, child processes (run_cmd), output cleaning, private files, locks
    config.py                the member's config, and the download and upload folder checks
    transport.py             ssh and rsync argv, the lockout, one login at a time
    scheduler.py             queue queries, cached per floor, and their parsing
    files.py                 the laptop side of get and put: scrub, place, snapshot
    tools.py                 the eight tools and their schemas
    protocol.py              JSON-RPC over stdio, the instructions Claude gets, cancellation
    admin.py                 install, doctor, reset, selftest; SETTINGS, SHIPPED, sudo line, gate
    agent/                   run in the agent account, sent byte for byte (comments live in sites.py)
      status.sh              the last 50 tasks and the agent's queue, as fixed fields
      start.sh               starts one task: claude-agent -p, detached
      cancel.sh              stops one task
    hooks/                   run by Claude Code itself, from the managed settings
      notify.sh              a notice when a turn of 30 s or more ends, or Claude waits for you
  tests/                     offline tests, never installed (see Upkeep)
    run_all.py               runs every offline test
    testkit.py               shared setup; refuses to start ssh; the managed file under a --home
    test_unit.py             unit checks, seconds (also hpc_mcp.py selftest)
    agent_sim.py             the agent scripts under local bash
    test_scheduler.py        Gadi cores, array jobs, Slurm listings, bash/zsh/tcsh login shells
    harness.py               real rsync on local folders, races, reset, install, doctor
    test_sshd.py             opt-in: the lockout and host keys against a real sshd on 127.0.0.1
    test_docs.py             the docs' generated tables, the file layout and every doc link
    claude_runs.py           opt-in: one real claude -p --model haiku run (run_all --claude: two)
    tee_mcp.py               logs MCP traffic for claude_runs --wrap
    live/                    tests you run against a real cluster
      kaiju_live.py          the live kit for your own Kaiju account
kaiju/                       Claude Code on Kaiju
  README.md                  members' guide, admin install and checks
  kaiju_claude_install.sh    admin: push the policy, install a version
  managed-settings.json      names the policy helper, nothing else -> /etc/claude-code/ on every node
  policy-helper              picks each account's rules -> /etc/claude-code/ on every node
  policy-helper.conf.in      group ids, filled in by `policy` -> /etc/claude-code/policy-helper.conf
  policies/                  -> /etc/claude-code/policies/ on every node
    human.json               rules for personal accounts
    human-next.json          stricter rules for personal accounts, installed last (agents/README.md)
    agent.json               rules for agent accounts
  CLAUDE.md                  standing instructions -> /etc/claude-code/ on every node
  CLAUDE-agent.md            agent accounts' extra instructions -> claudeMd in policies/agent.json
  claude-agent               starts Claude in an agent account -> /opt/cluster/software/claude-code/bin/
  modulefiles/               what Kaiju's module command reads
    claude-code/             module load claude-code
      current                the claude-code module -> /opt/cluster/modulefiles/claude-code/
  agents/                    agent accounts
    README.md                admin runbook
    MEMBER.md                for the member who owns one
    CHECKS.md                go/no-go checks for the first one
    kaiju-agent              admin: precheck, baseline, create, audit, suspend, resume, list
    kaiju-agent-netguard     optional: keeps agent accounts off the internal network
    kaiju-agent-watchdog     optional: caps agent accounts' Slurm jobs -> /usr/local/sbin/, cron
trial/                       a member's first job, Quick start step 7; never installed
  README.md                  what a job script needs on Gadi and Setonix, for the member's Claude
  uw3_trial.py               small Underworld3 Stokes model: prints TRIAL OK or TRIAL FAILED
```

## Upkeep

- **Update:** `git pull`, rerun `install` (it refuses uncommitted changes and prints the release
  sha256), rerun the sudo line if `doctor` fails the managed settings (until then `hpc` refuses
  every call), then `doctor`. A monthly `claude mcp get hpc` does a real handshake (local check).
- **Release sha256:** the sha256 of the `sha256  path` lines of the shipped files, sorted by path:

  ```bash
  cd ~/.local/share/uw3-hpc && find hpc_mcp.py managed-settings*.json codex-requirements.toml uw3hpc -type f | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256
  ```
- **Tests**, after every change: `/usr/bin/python3 -I laptop/tests/run_all.py` (offline, about
  2 min; never connects, never touches your `~/.ssh` or `~/.claude`).
  - `UW3HPC_SSHD_TEST=1` adds `test_sshd.py`, a real sshd on 127.0.0.1: logins, refusals, a
    banner without a final newline, and a host key the server offers after login.
  - `--claude PATH` adds two real `claude -p --model haiku` runs (they spend tokens, and exit early
    on a Mac with the managed file, whose allowlist blocks their temp server).
  - `test_docs.py` fails when the protected-paths (here) or caps (README.md) table drifts from its
    sources, the file layout and the repository differ, or a doc link breaks; `--write`
    regenerates the tables.
  - `test_scheduler.py` needs `/bin/zsh` and `/bin/tcsh` (stock macOS has both). `hpc_mcp.py
    selftest` runs only `test_unit`; an installed copy has no tests and exits 2.
- **Trial model:** `trial/uw3_trial.py` uses only calls in Underworld3 v3.1.0 and v3.2.0. When the
  shared images move to a new release, run the trial there once.
- **Hosts:** change `ADMIN` in `sites.py` and `deniedDomains` in `laptop/managed-settings.json`
  together (`test_unit` checks they agree); members rerun `install` and the sudo line.
- **Caps:** edit `ADMIN` in [laptop/uw3hpc/sites.py](laptop/uw3hpc/sites.py) (the tool
  descriptions and Claude's instructions follow), run
  `/usr/bin/python3 -I laptop/tests/test_docs.py --write` to refresh the table in
  [README.md](README.md#caps), run the tests, commit. Members `git pull` and rerun `install`.
- **Add an MCP server for members:** add `{"serverCommand": [the exact argv]}` (copy it from
  `claude mcp get NAME`; `${HOME}` is allowed) to `allowedMcpServers` in
  `laptop/managed-settings.json`, and commit (https servers need none: `https://*/*` admits them;
  any other URL needs a `serverUrl` entry).
  Members `git pull`, rerun `install`, then the sudo line; until they do, `doctor` reports
  `lacks allowedMcpServers` and `hpc` refuses every call. Never list a script inside a checkout:
  Claude can edit it, and it then runs unsandboxed with the ssh agent.
- **Code rules:**
  - Read the account paths and the runner as `util.HOME`, `util.CACHE`, `util.CONFIG`,
    `util.INSTALLED`, `util.OUT` and `util.run_cmd`, never `from .util import ...`: they are set
    at start (`--home`) or swapped by the tests, and an imported name keeps the old value.
  - A new module goes into `SHIPPED` in `admin.py`, or `install` leaves it out. `test_unit` checks
    both rules.
  - The agent scripts are sent byte for byte, so their comments live in `sites.py`.
    `/home/agent-share` is a literal in them and in `tools.py`.
  - `serve` refuses every call while `admin.managed_gate()` names a problem. A test that starts
    `serve` puts the account's own copy of the file under its `--home` (`testkit.managed_copy`),
    which only `--home` accepts.
- **`doctor`** never contacts a cluster. It checks: the prerequisites; the checkout matches its
  commit (WARN, run from a checkout); the `hpc` registration, exactly; the installed copy (exactly
  the shipped files, read-only, yours); the managed file ([as above](#the-managed-settings-file),
  and not group- or other-writable); no configuration profile outranks it, `$HOME` matches, and the
  terminal's agent is the login agent (WARNs); the config; each key's passphrase, and whether it is
  loaded and its hosts known (WARNs); `~/.claude/settings.json` and `additionalDirectories`; no
  Unix-socket setting reaching the agent. It cannot see the Claude Code copy VS Code bundles.
- **Protocol churn:** 39 of the 48 releases from 2.1.266 to 2.1.318 change MCP (local count); budget
  about one fix a year plus one port (inf). The server answers `server/discover` with -32601
  [CL 2.1.232, 2.1.318]; spec revision 2026-07-28 drops `initialize` [spec changelog].
- **Effort:** ~40 h to build, 16-28 h a year (estimates).

## Design record

| Approach | Build (est.) | Verdict |
|---|---|---|
| A. No code: ssh aliases + settings, raw ssh on ask | 4 h | Each ask depends on the member spotting `-o ProxyCommand` after the host. No rate limit or lockout. |
| B. Bash wrapper `hpc <site> <verb>` + site table | ~16 h | Not a boundary: an approved `run` is a shell. Blocking raw ssh needs an exact `excludedCommands` entry. No `wait`. |
| **C. MCP server, stdlib Python (chosen)** | ~40 h | Asks enforced in code in every mode, typed arguments with no command-text matching, a `wait` that does not block, floors shared on disk. Costs: a hand-written protocol layer on a changing spec, one server process per session. |
| D. Claude on the cluster | 8 h + an install and login per member per cluster | No policy we can enforce on national facilities; NCI login limits; results still need a download. Used on Kaiju, where we set the policy. |
| E. Hybrid: D on Kaiju, B on Gadi and Setonix | ~16 h | The 2026-11-05 recommendation. Approval fatigue on submit; downloads can steer the session. |

### Claude Code features relied on

*[mcp:N], [env:N], [perm:N], [modes:N], [sbx:N] and [setref:N] are lines in the
code.claude.com/docs/en pages mcp, env-vars, permissions, permission-modes, sandboxing and
settings-reference (copies saved 2026-11-03/05 outside the repo, so the lines drift as the pages
change). [managed] and [managed-mcp] are the pages managed-settings and managed-mcp (read
2026-11-09). [CL x] is the Claude Code changelog entry for x. [str] is the 2.1.314 binary strings.
[spec] is modelcontextprotocol.io/specification. [srt] is @anthropic-ai/sandbox-runtime 0.0.82's
`linux-sandbox-utils.js` (read 2026-11-12). [NCI] is the Gadi welcome page (updated 27 Feb
2024, marked "To be archived"). A tag without a number cites the page as read 2026-11-09.
(inf) means inference.*

| Item | Value | Source |
|---|---|---|
| Startup timeout | 30 s (`MCP_TIMEOUT`). No network calls at startup. | [env:493] |
| Wall clock per call | About 28 h (`MCP_TOOL_TIMEOUT`), or a per-server `timeout` of at least 1,000 ms. Progress does not extend it. | [mcp:452] |
| Idle limit (stdio) | Aborts after 30 min with no response or progress. A per-server `timeout` acts as a floor for it. | [mcp:454-456; env:331] |
| Auto-background | After 2 min, main conversation only. Lost on exit. | [mcp:466-481] |
| Output | Warns at 10k tokens. A result over 25k tokens is saved to a file, not cut. In the foreground, text over 50k chars also goes to a file. Error text over about 11k chars keeps only its first and last 5k. | [mcp:1501-1514] |
| Text cuts | Instructions 4,096 chars; descriptions loaded through search 16,384 | [mcp:1744-1746] |
| Rule syntax | `mcp__hpc__<tool>`. Allow rules take globs only after a literal `mcp__hpc__` (e.g. `mcp__hpc__get_*`). Deny and ask rules take any tool-name glob, `mcp__*` included. Rules with parentheses are skipped. Since 2.1.299, allow rules reach only the server they name. A bare deny or ask rule `mcp__hpc` still covers a server named `hpc__x`, so write one rule per tool. | [perm:121,193,205,581-583; CL 2.1.299] |
| `requiresUserInteraction` | Documented and in the binary. `dontAsk` mode denies the call. An allow from `--permission-prompt-tool` becomes a deny. VS Code is untested. | [mcp:1602-1608; str] |
| Probe | `server/discover` first, then `initialize` after an error or timeout. A server that is slow once is remembered for 7 days. The probe timeout looks like a third of the startup timeout (inf). | [CL 2.1.232, 2.1.292; str] |
| `readOnlyHint` | Calls run in parallel, so the server must be threaded | [mcp:1633] |
| Crashed server | Not restarted: `/mcp` → Reconnect. | [mcp:403] |
| Sandbox | Plain ssh cannot connect from sandboxed Bash, so ssh git remotes fail. `deniedDomains` holds in every mode and takes `*.domain` wildcards and IP literals. `Edit` deny rules also become the sandbox's `denyWrite`, and `Read` deny rules its `denyRead`; a project's `sandbox.filesystem.allowWrite` is ignored (sandboxing page, read 2026-11-09). MCP servers run outside the sandbox. | [sbx:43,582,611,920; setref:1396,2118] |
| Settings `env` | Reaches every subprocess, MCP servers included. Project and local settings cannot set `HOME`, `TMPDIR` or `XDG_*`, but can set `DEVELOPER_DIR`. | [setref:2370-2410] |
| Managed settings file | `/Library/Application Support/ClaudeCode/managed-settings.json`; nothing in user or project files or `--settings` overrides a managed key, and lists merge. A file the member cannot read is ignored; one that is not valid JSON stops Claude starting. A server-managed or MDM source outranks it. `managed-settings.d/*.json` (not hidden files) merge over it, later values winning. Server-managed settings that deliver a policy key also stop any `policyHelper` from running. The terminal, VS Code and the SDK all read it. | [managed; setref] |
| `allowedMcpServers` | A `serverCommand` matches every argument in order, not `env`; once one exists, every stdio server must match one. `${VAR}` in a policy entry expands from a pinned environment (2.1.219+). Built-ins (`ide`, Claude in Chrome) are exempt. | [managed-mcp] |
| CLI floor | The newest fix relied on is 2.1.292 (after 2.1.246 and 2.1.283) (inf). Use 2.1.316 or later, as tested on Kaiju. | [CL] |
