#!/bin/zsh
set -u

ROOT="/Users/gulfstream/Documents/GitHub/trading"
PYTHON="/usr/local/bin/python3"
PORT="8000"
SLEEP_SECONDS="30"
RESTART_DELAY="10"

cd "$ROOT" || exit 1
mkdir -p logs /tmp/trading_pycache

export PATH="/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONUNBUFFERED=1
export PYTHONPYCACHEPREFIX=/tmp/trading_pycache

log() {
  printf '%s supervisor %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')" "$*" >> logs/supervisor.log
}

log "started"

while true; do
  if /usr/sbin/lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    sleep "$SLEEP_SECONDS"
    continue
  fi

  log "starting run.py"
  "$PYTHON" -u run.py >> logs/bot.log 2>&1
  code=$?
  log "run.py exited code=$code; restart in ${RESTART_DELAY}s"
  sleep "$RESTART_DELAY"
done
