#!/bin/zsh
set -u

ROOT="/Users/gulfstream/Documents/GitHub/trading"
PYTHON="/usr/local/bin/python3"
PORT="8000"
SLEEP_SECONDS="30"
RESTART_DELAY="10"
LOG_STALE_SECONDS="1200"

cd "$ROOT" || exit 1
mkdir -p logs /tmp/trading_pycache

export PATH="/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONUNBUFFERED=1
export PYTHONPYCACHEPREFIX=/tmp/trading_pycache

log() {
  printf '%s supervisor %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')" "$*" >> logs/supervisor.log
}

bridge_ready_ok() {
  /usr/bin/curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/ready" | /usr/bin/grep -F '"ok":true' >/dev/null 2>&1
}

port_pids() {
  /usr/sbin/lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

pid_in_root() {
  local pid="$1"
  /usr/sbin/lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | /usr/bin/grep -Fx "n$ROOT" >/dev/null 2>&1
}

own_port_pids() {
  local pid
  for pid in ${(f)"$(port_pids)"}; do
    [[ -z "$pid" ]] && continue
    if pid_in_root "$pid"; then
      printf '%s\n' "$pid"
    fi
  done
}

own_port_busy() {
  [[ -n "$(own_port_pids)" ]]
}

log_fresh_ok() {
  [[ -f logs/bot.log ]] || return 1
  local mtime now age
  mtime="$(/usr/bin/stat -f %m logs/bot.log 2>/dev/null)" || return 1
  now="$(/bin/date +%s)"
  age=$((now - mtime))
  [[ "$age" -lt "$LOG_STALE_SECONDS" ]]
}

stop_own_port_processes() {
  local pid
  for pid in ${(f)"$(own_port_pids)"}; do
    [[ -z "$pid" ]] && continue
    log "stopping unhealthy run.py pid=$pid"
    /bin/kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 5
}

log "started"

while true; do
  if /usr/sbin/lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    if bridge_ready_ok && own_port_busy && log_fresh_ok; then
      sleep "$SLEEP_SECONDS"
      continue
    fi
    if own_port_busy; then
      log "own bridge/process unhealthy; restarting"
      stop_own_port_processes
      sleep "$RESTART_DELAY"
      continue
    fi
    log "port ${PORT} busy by non-project process; waiting"
    sleep "$SLEEP_SECONDS"
    continue
  fi

  log "starting run.py"
  "$PYTHON" -u run.py >> logs/bot.log 2>&1
  code=$?
  log "run.py exited code=$code; restart in ${RESTART_DELAY}s"
  sleep "$RESTART_DELAY"
done
