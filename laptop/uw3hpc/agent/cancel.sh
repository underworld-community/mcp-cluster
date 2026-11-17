d=$HOME/.hpc-tasks/$1
[ -d "$d" ] || { echo "ERR no-task"; exit 0; }; [ -e "$d/rc" ] && { echo "ERR finished"; exit 0; }
pid=$(cat "$d/pid" 2>/dev/null)
case $pid in ''|*[!0-9]*|0|1) echo "ERR no-pid"; exit 0 ;; esac
touch "$d/cancelled"; date +%s > "$d/end"
kill -TERM -- "-$pid" 2>/dev/null; pkill -TERM -s "$pid" 2>/dev/null
echo "OK $1"
squeue -h -u "$(id -un)" -o 'job %i %T %M'
