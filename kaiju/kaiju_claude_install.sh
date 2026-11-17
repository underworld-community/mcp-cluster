#!/bin/bash
#
# Install Claude Code for all Kaiju users, together with its cluster-wide policy.
#
#   ./kaiju_claude_install.sh 2.1.316    # push policy, then install that version and make it current
#   ./kaiju_claude_install.sh policy     # push the policy (helper, policies, CLAUDE.md), claude-agent and the modulefile only
#
# Run from the login node as an admin; the root-owned steps use sudo.
#
# Policy goes first so that a failure part-way never leaves a usable binary with
# no policy behind it. /etc is per node, so it is pushed to n1-n8 as well; a node
# that was down keeps a stale policy until `policy` is rerun.
#
# A node that is down stops the install. To go ahead without it, name it in
# SKIP_NODES (e.g. SKIP_NODES="n5" ./kaiju_claude_install.sh 2.1.316), then run
# `policy` once it is back; until then it keeps its old policy, if it had one.
#
# The binary is root-owned so neither users nor the agents they run can swap it,
# and it is never overwritten: a running session reads its executable from disk,
# so changing the file under it on NFS crashes the session (Bus error). An update
# installs beside the old versions and swaps the `current` symlink.

set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=/opt/cluster/software/claude-code
MODDIR=/opt/cluster/modulefiles/claude-code
BASE=https://downloads.claude.ai/claude-code-releases
KEY_URL=https://downloads.claude.ai/keys/claude-code.asc
PLATFORM=linux-x64
NODES=(n1 n2 n3 n4 n5 n6 n7 n8)
SSH_OPTS=(-o ConnectTimeout=10 -o BatchMode=yes)

# Members of these never get the agent policy (see policy-helper).
HUMAN_GROUPS=(wheel rsesit uw3admin ateam)
# Paths under /etc/claude-code, in install order: managed-settings.json must stay last.
POLICY_FILES=(policy-helper policy-helper.conf policies/human.json policies/agent.json
              CLAUDE.md managed-settings.json)

# Fingerprint as published in the setup docs at code.claude.com. Pinning it here
# means a key served from downloads.claude.ai is trusted only if it matches.
RELEASE_KEY=31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE

# platform-python ships with dnf on every RHEL 8 host, so JSON needs no extra package.
PY=/usr/libexec/platform-python

# Staged on local /tmp, not in the repo: if /home is root-squashed NFS, root cannot
# read a file under a 0700 home, so everything sudo copies comes from here.
STAGE=$(mktemp -d /tmp/claude-install.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

# Write to a hidden name, then rename: Claude Code reloads managed settings when
# they change, and a session that reads a half-written file runs without them.
put_root_file() {
    local src=$1 dst=$2 mode=$3
    sudo install -m "$mode" -o root -g root "$src" "$(dirname "$dst")/.$(basename "$dst").new"
    sudo mv -f "$(dirname "$dst")/.$(basename "$dst").new" "$dst"
}

# Resolved here, not on each node: the helper must see the gids the login node uses.
build_policy_conf() {
    local g gid gids=()
    for g in "${HUMAN_GROUPS[@]}"; do
        gid=$(getent group "$g" | head -n 1 | cut -d: -f3) || true
        [[ $gid =~ ^[0-9]+$ ]] \
            || { echo "group $g not found on $(hostname -s) — nothing installed" >&2; exit 1; }
        gids+=("$gid")
    done
    gid=$(getent group kaiju-agents | head -n 1 | cut -d: -f3) || true
    [ -z "$gid" ] || [ "$gid" = 7000 ] \
        || { echo "kaiju-agents has gid $gid but the policy expects 7000 — nothing installed" >&2; exit 1; }
    sed -e "s/@HUMAN_GIDS@/${gids[*]}/" -e "s/@HUMAN_GROUPS@/${HUMAN_GROUPS[*]}/" \
        "$HERE/policy-helper.conf.in" > "$STAGE/policy-helper.conf"
}

check_policy_helper() {   # helper, what a failure leaves unchanged
    local h=$1 out
    out=$(cd / && sudo -u nobody "$h") \
        || { echo "policy-helper fails for nobody — $2" >&2; exit 1; }
    printf '%s' "$out" | "$PY" -c 'import json, sys
assert json.load(sys.stdin) == {"managedSettings": json.load(open(sys.argv[1]))}' "$STAGE/policies/human.json" \
        || { echo "policy-helper does not give nobody the user policy — $2" >&2; exit 1; }
    if (cd / && sudo "$h") >/dev/null 2>&1; then
        echo "policy-helper does not refuse root — $2" >&2; exit 1
    fi
    if [[ $(id -un) == *-adm ]] && (cd / && "$h") >/dev/null 2>&1; then
        echo "policy-helper does not refuse $(id -un) — $2" >&2; exit 1
    fi
}

# Once managed-settings.json names the helper, replacing the helper or its files is live
# at once, so a rerun first tries a copy pointed at a root-owned scratch set of the new files.
check_staged_helper() {
    local c=/etc/claude-code/.check f
    sed -e "s|^CONF=/etc/claude-code/|CONF=$c/|" -e "s|^POLICIES=/etc/claude-code/|POLICIES=$c/|" \
        "$STAGE/policy-helper" > "$STAGE/policy-helper.check"
    [ "$(grep -c -e "^CONF=$c/" -e "^POLICIES=$c/" "$STAGE/policy-helper.check")" = 2 ] \
        || { echo "cannot point a test copy of policy-helper at $c — nothing installed" >&2; exit 1; }
    sudo rm -rf "$c"
    sudo install -d -m 0755 "$c" "$c/policies"
    sudo install -m 0755 -o root -g root "$STAGE/policy-helper.check" "$c/policy-helper"
    for f in policy-helper.conf policies/human.json policies/agent.json; do
        sudo install -m 0644 -o root -g root "$STAGE/$f" "$c/$f"
    done
    check_policy_helper "$c/policy-helper" "nothing installed"
    sudo rm -rf "$c"
}

install_policy() {
    local f
    for f in managed-settings.json policies/human.json policies/agent.json; do
        "$PY" -m json.tool "$HERE/$f" >/dev/null \
            || { echo "$f is not valid JSON — nothing installed" >&2; exit 1; }
    done
    install -d -m 0755 "$STAGE/policies"
    cp "$HERE/managed-settings.json" "$HERE/CLAUDE.md" "$HERE/policy-helper" "$HERE/claude-agent" "$STAGE/"
    cp "$HERE/policies/human.json" "$HERE/policies/agent.json" "$STAGE/policies/"
    # The agent text goes in as agent.json's claudeMd key: Claude Code documents only managedSettings in the
    # helper's output, and the helper is POSIX sh with no JSON tooling.
    "$PY" -c 'import json, sys
p = json.load(open(sys.argv[1]))
assert "claudeMd" not in p, "policies/agent.json sets claudeMd itself"
p["claudeMd"] = open(sys.argv[2], encoding="utf-8").read()
json.dump(p, open(sys.argv[1], "w"), indent=2)' "$STAGE/policies/agent.json" "$HERE/CLAUDE-agent.md" \
        || { echo "cannot add CLAUDE-agent.md to policies/agent.json — nothing installed" >&2; exit 1; }
    build_policy_conf
    sed -e 's|@HOME@|/home/x-agent|g' -e 's|@AGENT@|x-agent|g' "$STAGE/policies/agent.json" | "$PY" -c 'import json, sys
assert json.load(sys.stdin)["claudeMd"]' \
        || { echo "policies/agent.json is not valid JSON with claudeMd once filled in — nothing installed" >&2; exit 1; }

    sudo install -d -m 0755 /etc/claude-code /etc/claude-code/policies
    check_staged_helper
    for f in "${POLICY_FILES[@]}"; do
        # The installed copy too, before managed-settings.json first points at it.
        [ "$f" = managed-settings.json ] \
            && check_policy_helper /etc/claude-code/policy-helper "managed-settings.json left as it was"
        if [ "$f" = policy-helper ]; then
            put_root_file "$STAGE/$f" "/etc/claude-code/$f" 0755
        else
            put_root_file "$STAGE/$f" "/etc/claude-code/$f" 0644
        fi
    done

    local n ok=() failed=() skipped=() nobwrap=()
    for n in "${NODES[@]}"; do
        if [[ " ${SKIP_NODES:-} " == *" $n "* ]]; then
            skipped+=("$n")
            continue
        fi
        if push_policy_to "$n"; then
            ok+=("$n")
            sudo ssh "${SSH_OPTS[@]}" "$n" 'rpm -q bubblewrap socat' >/dev/null 2>&1 || nobwrap+=("$n")
        else
            failed+=("$n")
        fi
    done

    echo "policy:     /etc/claude-code/ on $(hostname -s) ${ok[*]}"
    [ ${#skipped[@]} -eq 0 ] \
        || echo "SKIPPED:    ${skipped[*]} (SKIP_NODES) — not updated; run \`$0 policy\` once back" >&2
    [ ${#nobwrap[@]} -eq 0 ] \
        || echo "            no bubblewrap/socat on ${nobwrap[*]}: Claude refuses to start there (sandbox.failIfUnavailable)"
    rpm -q bubblewrap socat >/dev/null \
        || { echo "bubblewrap/socat missing on $(hostname -s) — Claude will refuse to start: sudo dnf -y install bubblewrap socat" >&2; exit 1; }
    if [ ${#failed[@]} -gt 0 ]; then
        echo "FAILED to reach ${failed[*]} — not updated, nothing else installed." >&2
        echo "            Rerun when they are back, or skip them for now: SKIP_NODES=\"${SKIP_NODES:+$SKIP_NODES }${failed[*]}\" $0 ${MODE}" >&2
        exit 1
    fi

    sudo install -d -m 0755 "$DEST" "$DEST/bin"
    sudo install -m 0755 -o root -g root "$STAGE/claude-agent" "$DEST/bin/.claude-agent.new"
    sudo mv -f "$DEST/bin/.claude-agent.new" "$DEST/bin/claude-agent"
    echo "wrapper:    $DEST/bin/claude-agent"

    # Here, not with the binary: the modulefile puts claude-agent on PATH, so `policy`
    # alone must deliver it.
    cp "$HERE/modulefiles/claude-code/current" "$STAGE/modulefile"
    sudo install -d -m 0755 "$MODDIR"
    put_root_file "$STAGE/modulefile" "$MODDIR/current" 0644
    echo "module:     $MODDIR/current"
}

# Every file lands under a hidden name first; managed-settings.json is renamed last so
# it never names a helper that is not there yet.
push_policy_to() {
    local n=$1 f
    sudo ssh "${SSH_OPTS[@]}" "$n" 'install -d -m 0755 /etc/claude-code /etc/claude-code/policies' || return 1
    for f in "${POLICY_FILES[@]}"; do
        sudo scp "${SSH_OPTS[@]}" -q "/etc/claude-code/$f" "$n:/etc/claude-code/$(dirname "$f")/.$(basename "$f").new" \
            || return 1
    done
    sudo ssh "${SSH_OPTS[@]}" "$n" "cd /etc/claude-code && for f in ${POLICY_FILES[*]}; do
            d=\$(dirname \$f); b=\$(basename \$f); m=0644; [ \$f = policy-helper ] && m=0755
            chown root:root \$d/.\$b.new && chmod \$m \$d/.\$b.new && mv -f \$d/.\$b.new \$f || exit 1
        done"
}

verify_signature() {
    local ver=$1
    # A throwaway keyring holding only the downloaded key, so the check cannot be
    # satisfied by some other key the admin happens to trust.
    local gh="$STAGE/gnupg"
    install -d -m 0700 "$gh"
    curl -fsSL -o "$STAGE/release-key.asc" "$KEY_URL"
    curl -fsSL -o "$STAGE/manifest.json.sig" "$BASE/$ver/manifest.json.sig"
    gpg --homedir "$gh" --batch --quiet --import "$STAGE/release-key.asc" 2>/dev/null
    gpg --homedir "$gh" --batch --with-colons --fingerprint | grep -qx "fpr:::::::::${RELEASE_KEY}:" \
        || { echo "downloaded release key does not have fingerprint $RELEASE_KEY — not installed" >&2; exit 1; }
    # VALIDSIG ends with the primary key's fingerprint, whichever subkey signed.
    gpg --homedir "$gh" --batch --status-fd 1 --verify "$STAGE/manifest.json.sig" "$STAGE/manifest.json" 2>/dev/null \
        | grep -q "^\[GNUPG:\] VALIDSIG .* ${RELEASE_KEY}\$" \
        || { echo "manifest signature for $ver does not verify against $RELEASE_KEY — not installed" >&2; exit 1; }
    gpgconf --homedir "$gh" --kill gpg-agent 2>/dev/null || true
}

install_version() {
    local ver=$1 want sum bin
    curl -fsSL -o "$STAGE/manifest.json" "$BASE/$ver/manifest.json"
    if [ "${CLAUDE_INSTALL_SKIP_GPG:-0}" = 1 ]; then
        echo "WARNING:    CLAUDE_INSTALL_SKIP_GPG=1 — manifest signature NOT checked" >&2
    else
        verify_signature "$ver"
    fi

    curl -fsSL -o "$STAGE/claude" "$BASE/$ver/$PLATFORM/claude"
    want=$("$PY" -c 'import json, sys; print(json.load(open(sys.argv[1]))["platforms"][sys.argv[2]]["checksum"])' \
           "$STAGE/manifest.json" "$PLATFORM")
    sum=$(sha256sum "$STAGE/claude" | cut -d' ' -f1)
    [ "$sum" = "$want" ] \
        || { echo "checksum mismatch for $ver: got $sum, manifest says $want — not installed" >&2; exit 1; }

    bin="$DEST/$ver/bin/claude"
    if [ -e "$bin" ]; then
        [ "$(sha256sum "$bin" | cut -d' ' -f1)" = "$sum" ] \
            || { echo "$bin exists with different content — refusing to overwrite" >&2; exit 1; }
        echo "present:    $bin (identical) — reusing it"
    else
        # -d applies the mode to every operand; otherwise the admin's umask decides
        # $DEST and $DEST/$ver, and a private umask hides the install from users.
        sudo install -d -m 0755 "$DEST" "$DEST/$ver" "$DEST/$ver/bin"
        # Via a hidden name, so an interrupted copy never leaves a truncated `claude`.
        sudo install -m 0755 -o root -g root "$STAGE/claude" "$DEST/$ver/bin/.claude.new"
        sudo mv -Tf "$DEST/$ver/bin/.claude.new" "$bin"
    fi

    # Run the installed copy, not the one in /tmp, which may be mounted noexec.
    "$bin" --version >/dev/null \
        || { echo "$bin does not run — left in place, not made current" >&2; exit 1; }

    # ln -sfn unlinks first, leaving a window where the name does not resolve.
    sudo ln -sfn "$ver" "$DEST/.current.tmp"
    sudo mv -Tf "$DEST/.current.tmp" "$DEST/current"

    printf '%s  %-10s  %s  %s\n' "$(date -Is)" "$ver" "${sum:0:16}" "$USER" \
        | sudo tee -a "$DEST/MANIFEST" >/dev/null

    echo "installed:  $bin"
    echo "sha256:     $sum"
    echo "current:    $DEST/current -> $ver"
    echo "kept:       $(cd "$DEST" && ls -d [0-9]*/ | tr -d / | tr '\n' ' ')"
    echo "            Before removing an old version, check no session on ANY host runs it:"
    echo "            for h in localhost ${NODES[*]}; do sudo ssh \$h fuser -v $DEST/<old>/bin/claude; done"
}

MODE=${1:-}
if [ "${1:-}" = policy ]; then
    install_policy
elif [[ ${1:-} =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    install_policy
    install_version "$1"
else
    echo "usage: $0 <version, e.g. 2.1.316> | policy" >&2
    echo "newest release: $(curl -fsSL "$BASE/latest" 2>/dev/null || echo unknown)" >&2
    exit 1
fi
