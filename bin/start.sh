#!/usr/bin/env bash
# Brings up the whole Fathom app: preflight checks, explicit DB init, an FMP
# connectivity check, then both the backend (uvicorn --reload) and frontend
# (next dev) servers, each in its own process group so Ctrl-C here can stop
# both cleanly (see the trap near the bottom). Safe to re-run: refuses to
# double-start if bin/stop.sh hasn't been run against a still-live prior run.
#
# Run:
#   ./bin/start.sh
#
# Stop with Ctrl-C (foreground) or, from another shell / after disconnecting,
# ./bin/stop.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./common.sh
source "$SCRIPT_DIR/common.sh"

REQUIRED_ENV_KEYS=(FMP_API_KEY DATABASE_PATH CACHE_STALENESS_DAYS SEC_EDGAR_USER_AGENT)

BACKEND_READY_TIMEOUT_SECONDS=30
FRONTEND_READY_TIMEOUT_SECONDS=45

log() { echo "[start.sh] $*"; }
fail() {
  echo "[start.sh] ERROR: $*" >&2
  exit 1
}

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------

preflight() {
  local env_file="$BACKEND_DIR/.env"
  [[ -f "$env_file" ]] || fail "backend/.env not found. Copy backend/.env.example to backend/.env and fill in real values first."

  local missing=()
  for key in "${REQUIRED_ENV_KEYS[@]}"; do
    grep -qE "^${key}=" "$env_file" || missing+=("$key")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    fail "backend/.env is missing required key(s): ${missing[*]} (see backend/.env.example)."
  fi
  if ! grep -qE '^FMP_API_KEY=.+' "$env_file"; then
    fail "FMP_API_KEY in backend/.env is present but empty -- the app cannot fetch any data without it."
  fi

  command -v uv >/dev/null 2>&1 || fail "'uv' not found on PATH -- required to run the backend (https://docs.astral.sh/uv/)."
  command -v node >/dev/null 2>&1 || fail "'node' not found on PATH -- required to run the frontend."
  command -v npm >/dev/null 2>&1 || fail "'npm' not found on PATH -- required to run the frontend."

  if [[ -f "$BACKEND_PID_FILE" ]] && pid_group_alive "$(cat "$BACKEND_PID_FILE")"; then
    fail "Backend already running (pid $(cat "$BACKEND_PID_FILE")). Run ./bin/stop.sh first."
  fi
  if [[ -f "$FRONTEND_PID_FILE" ]] && pid_group_alive "$(cat "$FRONTEND_PID_FILE")"; then
    fail "Frontend already running (pid $(cat "$FRONTEND_PID_FILE")). Run ./bin/stop.sh first."
  fi

  log "Preflight OK: backend/.env present with required keys, uv/node/npm on PATH."
}

# ---------------------------------------------------------------------------
# 2. Explicit DB check
# ---------------------------------------------------------------------------

init_database() {
  log "Running init_db() explicitly..."
  (cd "$BACKEND_DIR" && uv run python -c "from core.db import init_db; init_db()") \
    || fail "Database initialization failed (see output above)."
  log "Database ready."
}

# ---------------------------------------------------------------------------
# 3. FMP connectivity check -- one cheap call, fails fast on a bad/missing key
# ---------------------------------------------------------------------------

check_fmp_connectivity() {
  log "Checking FMP connectivity (GET /quote for AAPL)..."
  (cd "$BACKEND_DIR" && uv run python -c '
import asyncio
import sys

from clients.fmp_client import fmp_client
from core.config import settings


async def main() -> None:
    if not settings.fmp_enabled:
        # FMP is deliberately paused -- the app must still be startable
        # cache-only (that is the whole point of FMP_ENABLED), so this
        # check is skipped rather than blocking startup on a live call
        # that would just be refused anyway. See the "Pausing the FMP
        # subscription" section in CLAUDE.md.
        print("FMP connectivity check skipped: FMP paused (FMP_ENABLED=false).")
        return
    if not settings.fmp_api_key:
        print("FMP_API_KEY is empty in backend/.env", file=sys.stderr)
        sys.exit(1)
    try:
        result = await fmp_client.get_quote("AAPL")
    except Exception as exc:  # noqa: BLE001 -- any failure here should fail startup with a clear message
        print(f"FMP request failed: {exc}", file=sys.stderr)
        sys.exit(1)
    if not result:
        print(f"FMP returned an empty/unexpected response: {result!r}", file=sys.stderr)
        sys.exit(1)
    print("FMP connectivity OK.")


asyncio.run(main())
') || fail "FMP connectivity check failed -- verify FMP_API_KEY in backend/.env is a real, active key."
}

# ---------------------------------------------------------------------------
# 4-6. Start both servers
# ---------------------------------------------------------------------------

start_backend() {
  mkdir -p "$(dirname "$BACKEND_LOG")"
  : > "$BACKEND_LOG"
  log "Starting backend (uvicorn --reload, host $BACKEND_HOST, port $BACKEND_PORT) -> $BACKEND_LOG"
  (cd "$BACKEND_DIR" && exec setsid uv run uvicorn core.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT" >>"$BACKEND_LOG" 2>&1 </dev/null) &
  BACKEND_PID=$!
  mkdir -p "$PID_DIR"
  echo "$BACKEND_PID" > "$BACKEND_PID_FILE"
}

start_frontend() {
  mkdir -p "$FRONTEND_LOG_DIR"
  : > "$FRONTEND_LOG"
  log "Starting frontend (next dev, port $FRONTEND_PORT) -> $FRONTEND_LOG"
  (cd "$FRONTEND_DIR" && exec setsid npm run dev -- -p "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1 </dev/null) &
  FRONTEND_PID=$!
  mkdir -p "$PID_DIR"
  echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"
}

wait_for_backend() {
  log "Waiting for backend to respond at $BACKEND_HEALTH_URL (timeout ${BACKEND_READY_TIMEOUT_SECONDS}s)..."
  local waited=0
  while (( waited < BACKEND_READY_TIMEOUT_SECONDS * 2 )); do
    if curl -fsS -o /dev/null "$BACKEND_HEALTH_URL" 2>/dev/null; then
      log "Backend is up."
      return 0
    fi
    if ! pid_group_alive "$BACKEND_PID"; then
      cleanup
      fail "Backend process exited before becoming healthy -- see $BACKEND_LOG."
    fi
    sleep 0.5
    waited=$((waited + 1))
  done
  cleanup
  fail "Backend did not respond within ${BACKEND_READY_TIMEOUT_SECONDS}s -- see $BACKEND_LOG."
}

wait_for_frontend() {
  log "Waiting for frontend to respond at $FRONTEND_URL (timeout ${FRONTEND_READY_TIMEOUT_SECONDS}s)..."
  local waited=0
  while (( waited < FRONTEND_READY_TIMEOUT_SECONDS * 2 )); do
    if curl -fsS -o /dev/null "$FRONTEND_URL" 2>/dev/null; then
      log "Frontend is up."
      return 0
    fi
    sleep 0.5
    waited=$((waited + 1))
  done
  # Soft failure only -- next dev's first-compile time varies a lot and
  # isn't itself a sign of misconfiguration the way a dead backend is.
  log "WARNING: frontend hasn't responded yet after ${FRONTEND_READY_TIMEOUT_SECONDS}s -- it may still be compiling. Check $FRONTEND_LOG."
}

# ---------------------------------------------------------------------------
# Cleanup / signal handling
# ---------------------------------------------------------------------------

cleanup() {
  trap - INT TERM EXIT
  log "Shutting down..."
  [[ -n "${TAIL_BACKEND_PID:-}" ]] && kill "$TAIL_BACKEND_PID" 2>/dev/null || true
  [[ -n "${TAIL_FRONTEND_PID:-}" ]] && kill "$TAIL_FRONTEND_PID" 2>/dev/null || true
  if [[ -n "${BACKEND_PID:-}" ]] && pid_group_alive "$BACKEND_PID"; then
    kill -TERM -- "-$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && pid_group_alive "$FRONTEND_PID"; then
    kill -TERM -- "-$FRONTEND_PID" 2>/dev/null || true
  fi
  rm -f "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"
  exit 0
}

main() {
  preflight
  init_database
  check_fmp_connectivity
  start_backend
  wait_for_backend
  start_frontend
  wait_for_frontend

  trap cleanup INT TERM EXIT

  log "Both servers are running. Backend: $BACKEND_HEALTH_URL | Frontend: $FRONTEND_URL"
  log "Backend pid (group): $BACKEND_PID | Frontend pid (group): $FRONTEND_PID"
  log "Logs: $BACKEND_LOG | $FRONTEND_LOG"
  log "Press Ctrl-C to stop both, or run ./bin/stop.sh from another shell."

  tail -n +1 -f "$BACKEND_LOG" | sed -u 's/^/[backend] /' &
  TAIL_BACKEND_PID=$!
  tail -n +1 -f "$FRONTEND_LOG" | sed -u 's/^/[frontend] /' &
  TAIL_FRONTEND_PID=$!

  # Wait for whichever of the two servers exits first -- not a blind `wait`
  # for every background job, which would hang forever on the `tail -f`
  # viewers even after both servers are gone (e.g. stopped externally via
  # ./bin/stop.sh from another shell, a documented supported workflow: that
  # sends TERM directly to the server process groups, not to this script,
  # so nothing here would otherwise notice). Whichever server exits first
  # (a crash, or an external stop) triggers tearing down the other one too,
  # so the pair is always managed together.
  wait -n "$BACKEND_PID" "$FRONTEND_PID"
  log "A server process exited -- shutting down the rest."
  cleanup
}

main "$@"
