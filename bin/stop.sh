#!/usr/bin/env bash
# Stops the backend and frontend servers started by bin/start.sh, using the
# PID files it writes to .run/. Safe to run anytime -- if a PID file is
# missing or its process is already gone, that service is reported as
# "nothing to stop" rather than erroring.
#
# Run:
#   ./bin/stop.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$SCRIPT_DIR/common.sh"

STOP_WAIT_SECONDS=10

log() { echo "[stop.sh] $*"; }

stop_one() {
  local name="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    log "$name: nothing to stop (no pid file)."
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"

  if ! pid_group_alive "$pid"; then
    log "$name: nothing to stop (pid $pid not running)."
    rm -f "$pid_file"
    return 0
  fi

  log "$name: stopping (pid $pid)..."
  kill -TERM -- "-$pid" 2>/dev/null

  local waited=0
  while pid_group_alive "$pid" && (( waited < STOP_WAIT_SECONDS * 2 )); do
    sleep 0.5
    waited=$((waited + 1))
  done

  if pid_group_alive "$pid"; then
    log "$name: still running after ${STOP_WAIT_SECONDS}s, sending SIGKILL..."
    kill -KILL -- "-$pid" 2>/dev/null
  fi

  rm -f "$pid_file"
  log "$name: stopped."
}

main() {
  stop_one "backend" "$BACKEND_PID_FILE"
  stop_one "frontend" "$FRONTEND_PID_FILE"
}

main "$@"
