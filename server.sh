#!/usr/bin/env bash
# Start, stop, and check on the app server.
#
#   ./server.sh start [port]   run in the background and open the browser
#   ./server.sh stop           shut it down
#   ./server.sh restart [port]
#   ./server.sh status
#   ./server.sh logs           follow the app's log (~/Library/Logs/<APP_NAME>/app.log)

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=app.conf
source "$APP_DIR/app.conf"
APP_TITLE="${APP_TITLE:-$APP_NAME}"

# Runtime files are deliberately not named after APP_NAME, so renaming the app
# while the server is running doesn't orphan it
PID_FILE="$APP_DIR/.server.pid"
PORT_FILE="$APP_DIR/.server.port"
LOG_FILE="$APP_DIR/.server.log"   # this run's console output (setup progress, library warnings)
# The app's persistent log (backend/log.py): timestamps, levels, rotated, kept across runs
if [[ "$(uname)" == Darwin ]]; then
  APP_LOG="$HOME/Library/Logs/$APP_NAME/app.log"
else
  APP_LOG="${XDG_STATE_HOME:-$HOME/.local/state}/$APP_NAME/app.log"
fi
DEFAULT_PORT="${PORT:-5900}"

# On first launch (and after requirements.txt changes) app.py creates .venv and
# pip-installs requirements.txt before it starts listening; the first time is
# about 40 MB of downloads (10 to 30 s normally); allow plenty for slow connections
START_TIMEOUT_SECS=600

running_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "$pid"
    return 0
  fi
  # Stale PID file from a crash or reboot
  rm -f "$PID_FILE" "$PORT_FILE"
  return 1
}

port_in_use() {
  # Python is already a requirement, so use it instead of lsof (not always installed on Linux)
  python3 -c 'import socket, sys; sys.exit(socket.socket().connect_ex(("127.0.0.1", int(sys.argv[1]))) != 0)' "$1"
}

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 || true
  else
    open "$1" 2>/dev/null || true
  fi
}

start() {
  local port="${1:-$DEFAULT_PORT}"
  local pid
  if pid="$(running_pid)"; then
    echo "$APP_TITLE is already running (PID $pid) at http://localhost:$(cat "$PORT_FILE")"
    open_browser "http://localhost:$(cat "$PORT_FILE")"
    return 0
  fi
  if port_in_use "$port"; then
    echo "Port $port is already in use by another program. Try: $0 start <port>" >&2
    return 1
  fi

  echo "Starting $APP_TITLE on port $port (log: ${LOG_FILE#"$APP_DIR"/})..."
  nohup python3 -u "$APP_DIR/app.py" "$port" >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  echo "$port" >"$PORT_FILE"

  # Wait for the server to start listening, showing what it logs meanwhile
  # (setting up .venv, installing dependencies, ExifTool), indented
  local started=$SECONDS quiet_since=$SECONDS shown=0 lines
  for _ in $(seq 1 $((START_TIMEOUT_SECS * 4))); do
    lines=$(wc -l <"$LOG_FILE" 2>/dev/null | tr -d ' ')
    if (( ${lines:-0} > shown )); then
      sed -n "$((shown + 1)),${lines}p" "$LOG_FILE" | show_log_lines
      shown=$lines
      quiet_since=$SECONDS
    elif (( SECONDS - quiet_since >= 5 )); then
      echo "  ...still starting ($((SECONDS - started)) s)"
      quiet_since=$SECONDS
    fi
    if port_in_use "$port"; then
      echo "$APP_TITLE started in $((SECONDS - started)) s (PID $(cat "$PID_FILE")) at http://localhost:$port"
      if grep -q 'downloading the latest release in the background' "$LOG_FILE" \
          && ! grep -q -E '^ExifTool [0-9]+\.[0-9]+ installed' "$LOG_FILE"; then
        echo "ExifTool is still downloading in the background; Exif Info uses its basic reader until it's done (follow it: $0 logs)."
      fi
      return 0
    fi
    if ! running_pid >/dev/null; then
      sed -n "$((shown + 1)),\$p" "$LOG_FILE" | show_log_lines >&2
      echo "$APP_TITLE failed to start; the log above says why (all of it: $0 logs)." >&2
      return 1
    fi
    sleep 0.25
  done
  echo "$APP_TITLE is running but not yet listening on port $port after $START_TIMEOUT_SECS s; check: $0 logs" >&2
}

# Log lines for the console: indented, without blank lines and the startup
# banner's box (the "started ... at http://..." line says the same)
show_log_lines() {
  grep -v -e '^[[:space:]]*$' -e '[╔╚║═]' | sed 's/^/  /'
}

stop() {
  local pid
  if ! pid="$(running_pid)"; then
    echo "$APP_TITLE is not running."
    return 0
  fi
  echo "Stopping $APP_TITLE (PID $pid)..."
  kill "$pid"
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "Server did not exit cleanly; forcing it."
    kill -9 "$pid"
  fi
  rm -f "$PID_FILE" "$PORT_FILE"
  echo "$APP_TITLE stopped."
}

status() {
  local pid
  if pid="$(running_pid)"; then
    echo "$APP_TITLE is running (PID $pid) at http://localhost:$(cat "$PORT_FILE")"
  else
    echo "$APP_TITLE is not running."
    return 1
  fi
}

case "${1:-}" in
  start)   start "${2:-}" ;;
  stop)    stop ;;
  restart) stop; start "${2:-}" ;;
  status)  status ;;
  logs)
    if [[ -f "$APP_LOG" ]]; then
      echo "Following $APP_LOG (Ctrl+C to stop)"
      tail -n 50 -f "$APP_LOG"
    else
      touch "$LOG_FILE"; tail -f "$LOG_FILE"
    fi
    ;;
  *)
    echo "Usage: $0 {start [port]|stop|restart [port]|status|logs}" >&2
    exit 1
    ;;
esac
