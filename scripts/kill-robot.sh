#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${THERAPY_ROBOT_RUNTIME_DIR-${LOG_DIR:-/tmp/therapy_robot}}"
PID_FILE="$RUNTIME_DIR/processes.pid"
LEGACY_PATTERN='main_core|main_control|main_motor|main_web_control|main_web_sim|main_web|main_sim'

if [[ ${#RUNTIME_DIR} -gt 4095 || "$RUNTIME_DIR" != /* || "$RUNTIME_DIR" == "/" ||
      "$RUNTIME_DIR" == */ || "$RUNTIME_DIR" == *//* || "$RUNTIME_DIR" == */./* ||
      "$RUNTIME_DIR" == */../* || "$RUNTIME_DIR" == */. || "$RUNTIME_DIR" == */.. ||
      ! "$RUNTIME_DIR" =~ ^/[A-Za-z0-9_./-]+$ ]]; then
  echo "invalid THERAPY_ROBOT_RUNTIME_DIR: expected a safe non-root absolute path" >&2
  exit 2
fi

legacy_kill() {
  pkill -TERM -f "$LEGACY_PATTERN" 2>/dev/null || true
  for _ in $(seq 1 50); do
    if ! pgrep -f "$LEGACY_PATTERN" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.02
  done
  echo "warning: legacy robot processes did not stop within 1 second; forcing termination" >&2
  pkill -KILL -f "$LEGACY_PATTERN" 2>/dev/null || true
}

if [[ ! -f "$PID_FILE" ]]; then
  if [[ "$RUNTIME_DIR" == "/tmp/therapy_robot" ]]; then
    legacy_kill
  fi
  exit 0
fi

process_matches() {
  local pid="$1"
  local expected_start="$2"
  local expected_name="$3"
  local actual_start
  local executable

  case "$expected_name" in
    main_core|main_control|main_motor|main_sim|main_web_control|main_web_sim) ;;
    *) return 1 ;;
  esac
  [[ "$pid" =~ ^[0-9]+$ && "$expected_start" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/$pid/stat" ]] || return 1
  actual_start="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
  [[ "$actual_start" == "$expected_start" ]] || return 1
  executable="$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)"
  [[ -n "$executable" && "${executable##*/}" == "$expected_name" ]]
}

declare -a REGISTERED=()
while read -r pid start_time name extra; do
  [[ -z "${extra:-}" ]] || continue
  if process_matches "$pid" "$start_time" "$name"; then
    kill -TERM "$pid" 2>/dev/null || true
    REGISTERED+=("$pid:$start_time:$name")
  fi
done < "$PID_FILE"

for _ in $(seq 1 50); do
  remaining=0
  for record in "${REGISTERED[@]}"; do
    IFS=: read -r pid start_time name <<< "$record"
    if process_matches "$pid" "$start_time" "$name"; then
      remaining=1
    fi
  done
  [[ "$remaining" -eq 0 ]] && break
  sleep 0.02
done

for record in "${REGISTERED[@]}"; do
  IFS=: read -r pid start_time name <<< "$record"
  if process_matches "$pid" "$start_time" "$name"; then
    echo "warning: $name pid $pid did not stop within 1 second; forcing termination" >&2
    kill -KILL "$pid" 2>/dev/null || true
  fi
done

rm -f -- "$PID_FILE"
