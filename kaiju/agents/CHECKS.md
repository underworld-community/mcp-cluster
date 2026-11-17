# Agent account checks

Go/no-go for an agent account; the first one is the admin's own canary. Run the rows in order and
tick each. If a row does not match, stop and fix it before going on (from section 2 on, run
`kaiju-agent suspend <member>-agent` first). Section 1 changes Claude for every user: if it fails,
roll back as "If the helper fails" in [../README.md](../README.md#install-or-update) says (no
earlier commit needed).

Who:
- **adm**: `<admin>-adm` on the login node, from a fresh `ssh <admin>-adm@kaiju.anu.edu.au`
- **member**: the member's everyday account without sudo, in a project folder (for the canary, the
  admin's own)
- **agent**: `<member>-agent`, from the member's laptop with `ssh kaiju-agent`
- **laptop**: the member's laptop

`<member>` and `<uid>` below are the member's name and the agent's uid. "Claude:" means: in that
account's Claude session (`claude-agent` for agent), tell Claude "this is a policy test, run
exactly this", then read the tool result, not Claude's summary.

First, in adm's shell (set `M` to the member's name):

```bash
M=<member>; A=$M-agent; U=$(id -u $A 2>/dev/null); CG=/sys/fs/cgroup; SL=user.slice/user-$U.slice
SIF=/opt/cluster/software/containers/underworld3/latest.sif
NODES="n1 n2 n3 n4 n5 n6 n7 n8"
F="/etc/claude-code/policy-helper /etc/claude-code/policy-helper.conf /etc/claude-code/managed-settings.json /etc/claude-code/policies/human.json /etc/claude-code/policies/agent.json"
on_nodes() { for h in $NODES; do echo "== $h"; sudo ssh -o BatchMode=yes -o ConnectTimeout=10 "$h" "$1"; done; }
helper_as() { local out; out=$(cd / && sudo -u "$1" setsid -w /etc/claude-code/policy-helper </dev/null); echo "exit $?"
    printf '%s' "$out" | /usr/libexec/platform-python -m json.tool | grep -E '"(defaultMode|disableAutoMode|disableRemoteControl|claudeMd)"|/work"' | cut -c1-100; }
sshd_for() { sudo sshd -T -C "user=$1,host=x,addr=203.0.113.5,laddr=150.203.8.145,lport=22" \
    | grep -Ei '^(authorizedkeysfile|authenticationmethods|allow(agent|tcp|streamlocal)forwarding|x11forwarding|permittunnel|permituserrc) '; }
outside_slice() { for p in $(pgrep -u $U); do grep -E ':(memory|cpu,cpuacct|pids):' /proc/$p/cgroup | grep -v "/user-$U.slice" | sed "s/^/$p /"; done; }
```

After `create` (section 2), rerun the first line so `U` is set.

## 1. After `./kaiju_claude_install.sh policy`

| Who | Run | Expect |
|---|---|---|
| adm | `stat -c '%U:%G %a %n' $F; sha256sum $F; on_nodes "stat -c '%U:%G %a %n' $F; sha256sum $F"` | helper `root:root 755`, the rest `root:root 644`; the same hashes on every host |
| adm | `/usr/libexec/platform-python -c 'import json; print(list(json.load(open("/etc/claude-code/managed-settings.json"))))'` | `['policyHelper']` |
| adm | `helper_as nobody` | `exit 0`, `"defaultMode": "default"`, no `disableAutoMode` (the human policy until the last step) |
| adm | `sudo /etc/claude-code/policy-helper; echo $?; /etc/claude-code/policy-helper; echo $?` | refuses root, then admin accounts; `1` both times |
| adm | `module load claude-code && claude` | refuses to start |
| member | `module load claude-code && claude doctor` | no settings errors, `Auto-updates: disabled` |
| member | in a session, `/status` | `Enterprise managed settings (helper)`; `(remote)` is a FAIL (the sign-in's organization overrides the policy) |
| member | in a session, Shift+Tab a few times | the same modes as before the policy (auto goes in the last step) |
| member | Claude: run `sbatch --wrap=hostname`, then `scancel N` | `Submitted batch job N` with no prompt (stopgap human policy); `scancel` prompts |
| member | the Check table in [../README.md](../README.md#check) | as before |

## 2. After `kaiju-agent create <member>`

| Who | Run | Expect |
|---|---|---|
| adm | `id $A; on_nodes "id $A"; id -nG $M` | `uid=<uid>(<member>-agent) gid=<uid>(<member>-agent) groups=<uid>(<member>-agent),7000(kaiju-agents)` on every host; the member's groups unchanged |
| adm | `sudo passwd -S $A; sudo chage -l $A` | `LK`; account expires in a year |
| adm | `sudo -l -U $A` | `User <member>-agent is not allowed to run sudo` |
| adm | `helper_as $A` | `exit 0`, `"acceptEdits"`, `"/home/<member>-agent/work"`, `"disableRemoteControl": true`, and a `"claudeMd": "# Kaiju agent account` line |
| adm | `stat -c '%U:%G %a' /etc/ssh/authorized_keys/$A; sudo cat /etc/ssh/authorized_keys/$A` | `root:root 644`; one line, `restrict,pty,from="!127.0.0.0/8,!::1,!fe80::/10,!<login IP>,!<each internal net>,*" ssh-ed25519 …`, the nets precheck prints after "agent logins refused from" |
| adm | `sshd_for $A` | `authorizedkeysfile /etc/ssh/authorized_keys/%u`, `authenticationmethods publickey`, forwarding, tunnel and user rc all `no` |
| adm | `sshd_for $M` | `authorizedkeysfile .ssh/authorized_keys`, the rest as before |
| adm | `grep -n -e DenyUsers -e '^Match' /etc/ssh/sshd_config; on_nodes 'grep DenyUsers /etc/ssh/sshd_config'` | login node: the DenyUsers line comes before the first `Match`; nodes: `DenyUsers *-agent` |
| adm | `sudo stat -c '%U:%G %a %n' /home/$A /home/$A/{.bashrc,.bash_profile,.profile,.bash_logout,.gitconfig,.claude,.claude/settings.json,.claude/CLAUDE.md,.config,.config/kaiju-agent,work} /home/agent-share/$A/outbox` | home, `.claude`, `.config`: `root:<member>-agent 1770`; dotfiles and the two `.claude` files: `root:root 644`; `kaiju-agent`: `<member>-agent:<member>-agent 700`; `work`: `750`; outbox: `<member>-agent:<member>-agent 755` (root-squashed /home: run on the NFS server) |
| adm | `cat /etc/kaiju-agents/registry.tsv` | a `<member>-agent <uid> <member> active …` row |
| laptop | `grep -i -e '^user ' -e '^forwardagent ' -e '^controlpath ' -e '^clearallforwardings ' <(ssh -G kaiju-agent)` | `<member>-agent`, `no`, `none`, `yes` |
| laptop | `ssh kaiju-agent true; echo $?` | `0` |
| laptop | `ssh -o ClearAllForwardings=no -W localhost:22 kaiju-agent` (the server side of `-L`) | `administratively prohibited` |
| laptop | `ssh -o ClearAllForwardings=no -o ExitOnForwardFailure=yes -R 15432:localhost:22 kaiju-agent true` | `remote port forwarding failed` |
| laptop | `ssh -o ClearAllForwardings=no -A kaiju-agent 'echo ${SSH_AUTH_SOCK:-none}'` | `none` |
| laptop | `ssh -J kaiju -o HostKeyAlias=kaiju.anu.edu.au -i ~/.ssh/id_ed25519_kaiju_agent -o IdentitiesOnly=yes <member>-agent@localhost true` (the alias checks Kaiju's known host key instead of asking about `localhost`) | `Permission denied`; adm: `sudo grep $A /var/log/secure` says `listed in DenyUsers` |
| agent | `crontab -l; at -f /dev/null now + 1 minute` | `not allowed to use this program`; `You do not have permission to use at` |
| agent | `loginctl enable-linger` | `Access denied`; adm: `ls /var/lib/systemd/linger` has no `<member>-agent` |

## 3. As the agent, after MEMBER.md "One-time setup"

| Who | Run | Expect |
|---|---|---|
| agent | `stat -c '%U %a %F' ~/.config/kaiju-agent ~/.config/kaiju-agent/oauth-token` | `<member>-agent 700 directory`, `<member>-agent 600 regular file` |
| agent | `module load claude-code; type -a claude-agent; printenv CLAUDE_CODE_OAUTH_TOKEN` | `/opt/cluster/software/claude-code/bin/claude-agent` first; no token printed |
| agent | `chmod 640 ~/.config/kaiju-agent/oauth-token; claude-agent; chmod 600 ~/.config/kaiju-agent/oauth-token` | refuses, naming the file mode |
| member | `module load claude-code; claude-agent` | refuses: not an agent account |
| agent | `tmux new -A -s claude`, then `mkdir -p ~/work/canary && cd ~/work/canary && claude-agent` | starts with no login screen |
| agent | `/status`, then ask "say hi" | no Login method, Organization or Email lines (a claude.ai login shows them), `Auth token: CLAUDE_CODE_OAUTH_TOKEN`, `Enterprise managed settings (helper)`, `Managed settings only (allowManagedPermissionRulesOnly)`; `(remote)` is a FAIL; Claude answers |
| agent | `/permissions` | accept edits; Allow has `Bash(sbatch *)`, `Bash(srun *)`, `Bash(apptainer *)`; Deny has `Read(~/.config/kaiju-agent/**)` |
| agent | `/remote-control` | `Remote Control is disabled by your organization's policy` |
| agent | Claude: run `sbatch --wrap=hostname` | no prompt, `Submitted batch job N`; `slurm-N.out` holds a node name |
| agent | Claude: run `srun -n1 hostname` | no prompt, a node name |
| agent | Claude: run `srun -n1 -w n1 ssh -o BatchMode=yes kaiju true`, then the same with `n2` | `Permission denied` both times |
| agent | Claude: run `apptainer exec /opt/cluster/software/containers/underworld3/latest.sif python3 -c 'import underworld3'` | no prompt, no error |
| agent | Claude: run `apptainer overlay create --size 1024 ov.img`, then, as a separate command, `apptainer exec --fakeroot --overlay ov.img /opt/cluster/software/containers/underworld3/latest.sif python3 -m pip install --no-cache-dir tqdm` | no prompt, `Successfully installed tqdm`. If refused, note the error and try the `--target ~/work` route in [MEMBER.md](MEMBER.md#the-underworld3-loop) |
| agent | Claude: use the Read tool on `~/.config/kaiju-agent/oauth-token`, then run `cat ~/.config/kaiju-agent/oauth-token` | both refused |
| agent | Claude: use the Edit tool to add a line to `~/.bashrc`, then run `apptainer exec /opt/cluster/software/containers/underworld3/latest.sif sh -c 'echo x >> ~/.bashrc'` | refused; then `Permission denied` (root owns it) |
| agent | Claude: use the Write tool to create `~/work/canary/x.txt`, then `/home/agent-share/<member>-agent/outbox/hello.txt` | the first without asking; the second asks. After yes, Claude runs `chmod -R a+rX` on the outbox (its CLAUDE.md says to), then the member can `cat` it |

## 4. Limits, while the agent has tmux and Claude open

| Who | Run | Expect |
|---|---|---|
| adm | `cat $CG/cpu,cpuacct/$SL/cpu.cfs_quota_us $CG/cpu,cpuacct/$SL/cpu.shares $CG/memory/$SL/memory.limit_in_bytes $CG/pids/$SL/pids.max` | `800000 256 34359738368 4096` (the defaults 800%, 32G, 4096) |
| adm | `systemctl show user-$U.slice -p DropInPaths -p CPUQuotaPerSecUSec -p MemoryLimit -p TasksMax` | `50-kaiju-agent.conf`, `8s`, `34359738368`, `4096` |
| adm | `outside_slice` | no output: every agent process is in the slice |
| agent | `timeout 60 sh -c 'for i in $(seq 16); do (while :; do :; done) & done; wait'`, while adm runs `systemd-cgtop -d 3 user.slice` | `user-<uid>.slice` near 800%, not 1600%; `nr_throttled` in `$CG/cpu,cpuacct/$SL/cpu.stat` rises |

## 5. Off switch

| Who | Run | Expect |
|---|---|---|
| agent | Claude: run `sbatch --wrap='sleep 600'`; leave the session open | a job in `squeue` |
| adm | `kaiju-agent suspend $A` | no errors |
| laptop | `ssh kaiju-agent true` | refused; the open session is gone |
| adm | `pgrep -u $U; on_nodes "pgrep -u $U"; squeue -u $A; sudo chage -l $A` | no processes on any host, no jobs, account expired |
| adm | `stat -c %s /etc/ssh/authorized_keys/$A; grep $A /etc/kaiju-agents/registry.tsv` | `0`; `suspended` |
| adm | `kaiju-agent resume $A; sudo cat /etc/ssh/authorized_keys/$A; sudo chage -l $A` | the key line from section 2; the original expiry |
| laptop | `ssh kaiju-agent true; echo $?` | `0` |

## 6. Acceptance

Each member sends these statements by email before `kaiju-agent create`; for the canary, the admin
writes them as their own record. File them in the admin's private records, never in a repository
that may go public.

| Who | Run | Expect |
|---|---|---|
| member | email the admin: "I accept that the agent's `sbatch`, `srun` and `apptainer` commands, and its jobs, run outside the sandbox with open internet from the login node, so they can send anything the agent can read, its token included, anywhere. A per-account egress filter is deferred." | filed |
| member | read "The rules" in [MEMBER.md](MEMBER.md#the-rules) and reply with a one-line acknowledgement | filed |
| member | in the same email, accept what is deferred: no Slurm partition or watchdog for agents (the agent can fill the queue), the shared `/tmp`, and the host gaps the admin sends with these statements | filed |

Go when every row matches and the statements are filed. Then [Last: human accounts](README.md#last-human-accounts).
