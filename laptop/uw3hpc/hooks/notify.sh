#!/bin/sh
# Claude Code's notification hooks, from the managed settings: a notice when a turn of 30 s or more ends, and when
# Claude waits for you. Hooks run outside the sandbox with a project's settings env, so every command is an absolute
# path, and the notice holds only fixed words, a number and the folder name cut to safe characters.
event=$1
sid=$(/usr/bin/tr -d '\n' | /usr/bin/sed -n 's/.*"session_id" *: *"\([A-Za-z0-9-]*\)".*/\1/p')
stamp="${TMPDIR:-/tmp}/uw3hpc-turn-${sid:-none}"
name=$(/usr/bin/basename "${CLAUDE_PROJECT_DIR:-$PWD}" | /usr/bin/tr -cd 'A-Za-z0-9._-' | /usr/bin/cut -c1-40)

notify() {
    if [ -x /usr/bin/osascript ]; then
        /usr/bin/osascript -e "display notification \"$1\" with title \"Claude Code\" sound name \"$2\"" 2>/dev/null
    elif [ -x /usr/bin/notify-send ]; then
        /usr/bin/notify-send "Claude Code" "$1" 2>/dev/null
    fi
}

case $event in
    start) /bin/date +%s > "$stamp" 2>/dev/null ;;
    stop)
        start=$(/bin/cat "$stamp" 2>/dev/null | /usr/bin/tr -cd 0-9)
        took=$(( $(/bin/date +%s) - ${start:-0} ))
        [ "${start:-0}" -gt 0 ] && [ "$took" -ge 30 ] && notify "Done in $name after ${took}s" Glass ;;
    wait) notify "Waiting for your input in $name" Ping ;;
esac
exit 0
