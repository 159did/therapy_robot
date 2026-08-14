#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-}"
RUNTIME_DIR="${THERAPY_ROBOT_RUNTIME_DIR-${LOG_DIR:-/tmp/therapy_robot}}"
LOG_DIR="${LOG_DIR:-$RUNTIME_DIR}"
if [[ ${#RUNTIME_DIR} -gt 4095 || "$RUNTIME_DIR" != /* || "$RUNTIME_DIR" == "/" ||
      "$RUNTIME_DIR" == */ || "$RUNTIME_DIR" == *//* || "$RUNTIME_DIR" == */./* ||
      "$RUNTIME_DIR" == */../* || "$RUNTIME_DIR" == */. || "$RUNTIME_DIR" == */.. ||
      ! "$RUNTIME_DIR" =~ ^/[A-Za-z0-9_./-]+$ ]]; then
  echo "invalid THERAPY_ROBOT_RUNTIME_DIR: expected a safe non-root absolute path" >&2
  exit 2
fi
export THERAPY_ROBOT_RUNTIME_DIR="$RUNTIME_DIR"

case "$MODE" in
  sim)
    if [[ -x "$ROOT_DIR/bin/main_core" ]]; then
      RUNNER="$ROOT_DIR/scripts/run-jetson-sim.sh"
    else
      RUNNER="$ROOT_DIR/scripts/run-host.sh"
    fi
    ;;
  hardware)
    RUNNER="$ROOT_DIR/scripts/run-jetson-hardware.sh"
    ;;
  *)
    echo "usage: $0 sim|hardware" >&2
    exit 2
    ;;
esac

mkdir -p "$LOG_DIR"
printf '%s\n' "$MODE" > "$LOG_DIR/requested_run_mode"
exec "$RUNNER" >"$LOG_DIR/mode_switch_${MODE}.log" 2>&1
