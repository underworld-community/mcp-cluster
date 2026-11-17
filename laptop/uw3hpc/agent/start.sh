id=$1 project=$2 session=$3 T=$HOME/.hpc-tasks w=$HOME/work/$2 o=/home/agent-share/$(id -un)/outbox/$1
[ -d "$w" ] || { echo "ERR no-project"; exit 0; }; umask 077; mkdir -p "$T" || { echo "ERR taskdir"; exit 0; }
for d in "$T"/t*; do
  [ -e "$d/rc" ] || [ -e "$d/cancelled" ] || [ "$(cat "$d/project" 2>/dev/null)" != "$project" ] \
    || ! kill -0 "$(cat "$d/pid" 2>/dev/null)" 2>/dev/null || { echo "ERR busy ${d##*/}"; exit 0; }
done
d=$T/$id; mkdir "$d" || { echo "ERR exists"; exit 0; }
cat > "$d/prompt"; echo "$project" > "$d/project"; echo "$session" > "$d/session"; date +%s > "$d/start"
(umask 022; mkdir -p "$o") || { echo "ERR outbox"; exit 0; }
cd "$w" || { echo "ERR no-project"; exit 0; }
setsid bash -c 'echo $$ > "$1/pid"; exec bash -lc "$0" task "$@"' '"$3" -p --session-id "$2" --add-dir "$4" \
  --output-format json < "$1/prompt" > "$1/out.json" 2> "$1/err"; echo $? > "$1/rc"; date +%s > "$1/end"' \
  "$d" "$session" "$4" "$o" < /dev/null > /dev/null 2>&1 &
for i in 1 2 3 4 5 6 7 8 9 10; do [ -s "$d/pid" ] && break; sleep 0.5; done
echo "OK $id $session"
