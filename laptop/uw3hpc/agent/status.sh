T=$HOME/.hpc-tasks O=/home/agent-share/$(id -un)/outbox
for i in $(ls -1 "$T" 2>/dev/null | tail -n 50); do d=$T/$i st=unknown
  rc=$(cat "$d/rc" 2>/dev/null) pid=$(cat "$d/pid" 2>/dev/null)
  if [ -e "$d/cancelled" ]; then st=cancelled; elif [ -n "$rc" ]; then st=failed; [ "$rc" = 0 ] && st=done
  elif [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then st=running; fi
  f() { cat "$d/$1" 2>/dev/null || echo -; }
  echo "task $i $st ${rc:--} $(f start) $(f end) $(f session) $(f project)" \
    $(find "$O/$i" -type f -printf '%s\n' 2>/dev/null | awk '{n++; b+=$1} END {print n+0, b+0}')
done
squeue -h -u "$(id -un)" -o 'job %i %T %M'
