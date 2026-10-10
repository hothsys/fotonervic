#!/usr/bin/env bash
# Start, stop, and check on the app server.
#
#   ./server.sh start [port]   run in the background and open the browser
#   ./server.sh stop           shut it down
#   ./server.sh restart [port]
#   ./server.sh status
#   ./server.sh logs           follow the server log

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=app.conf
source "$APP_DIR/app.conf"
APP_TITLE="${APP_TITLE:-$APP_NAME}"

# Runtime files are deliberately not named after APP_NAME, so renaming the app
# while the server is running doesn't orphan it
PID_FILE="$APP_DIR/.server.pid"
PORT_FILE="$APP_DIR/.server.port"
LOG_FILE="$APP_DIR/.server.log"
DEFAULT_PORT=5900

# app.py pip-installs missing dependencies before it starts listening, so the
# first launch can take a while (rawpy is a large download)
START_TIMEOUT_SECS=120

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

  nohup python3 -u "$APP_DIR/app.py" "$port" >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  echo "$port" >"$PORT_FILE"

  # Wait for the server to start listening
  for _ in $(seq 1 $((START_TIMEOUT_SECS * 4))); do
    if port_in_use "$port"; then
      echo "$APP_TITLE started (PID $(cat "$PID_FILE")) at http://localhost:$port"
      return 0
    fi
    if ! running_pid >/dev/null; then
      echo "$APP_TITLE failed to start. Last log lines:" >&2
      tail -n 20 "$LOG_FILE" >&2
      return 1
    fi
    sleep 0.25
  done
  echo "$APP_TITLE is running but not yet listening on port $port; check: $0 logs" >&2
}

stop() {
  local pid
  if ! pid="$(running_pid)"; then
    echo "$APP_TITLE is not running."
    return 0
  fi
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
  logs)    touch "$LOG_FILE"; tail -f "$LOG_FILE" ;;
  *)
    echo "Usage: $0 {start [port]|stop|restart [port]|status|logs}" >&2
    exit 1
    ;;
esac
