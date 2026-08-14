#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
SHM_NAME="${THERAPY_ROBOT_SHM_NAME-/therapy_robot_shared_state}"
if [[ ${#SHM_NAME} -gt 255 || "$SHM_NAME" == "/." || "$SHM_NAME" == "/.." || ! "$SHM_NAME" =~ ^/[A-Za-z0-9_.-]+$ ]]; then
  echo "invalid THERAPY_ROBOT_SHM_NAME: expected '/' followed by 1-254 safe characters" >&2
  exit 2
fi
SHM_PATH="/dev/shm/${SHM_NAME#/}"
export THERAPY_ROBOT_SHM_NAME="$SHM_NAME"
WEB_PORT="${THERAPY_ROBOT_WEB_PORT:-8080}"
SIM_WEB_PORT="${THERAPY_ROBOT_SIM_WEB_PORT:-8081}"
if [[ ! "$WEB_PORT" =~ ^[0-9]+$ || ${#WEB_PORT} -gt 5 ||
      ! "$SIM_WEB_PORT" =~ ^[0-9]+$ || ${#SIM_WEB_PORT} -gt 5 ]]; then
  echo "invalid web port: expected an integer from 1 to 65535" >&2
  exit 2
fi
WEB_PORT=$((10#$WEB_PORT))
SIM_WEB_PORT=$((10#$SIM_WEB_PORT))
if (( WEB_PORT < 1 || WEB_PORT > 65535 || SIM_WEB_PORT < 1 || SIM_WEB_PORT > 65535 )); then
  echo "invalid web port: expected an integer from 1 to 65535" >&2
  exit 2
fi
export THERAPY_ROBOT_WEB_PORT="$WEB_PORT"
export THERAPY_ROBOT_SIM_WEB_PORT="$SIM_WEB_PORT"
export THERAPY_ROBOT_COLLISION_CONFIG="${THERAPY_ROBOT_COLLISION_CONFIG:-$ROOT_DIR/config/enclosure-collision.csv}"
export THERAPY_ROBOT_COLLISION_REQUIRED="${THERAPY_ROBOT_COLLISION_REQUIRED:-0}"
mkdir -p "$LOG_DIR" "$RUNTIME_DIR"
"$ROOT_DIR/scripts/kill-robot.sh" || true
rm -f "$SHM_PATH"
PID_FILE="$RUNTIME_DIR/processes.pid"
: > "$PID_FILE"

LAST_STARTED_PID=""
start_component() {
  local name="$1"
  shift
  "$@" > "$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  local start_time
  start_time="$(awk '{print $22}' "/proc/$pid/stat")"
  printf '%s %s %s\n' "$pid" "$start_time" "$name" >> "$PID_FILE"
  LAST_STARTED_PID="$pid"
}
export LD_LIBRARY_PATH="$ROOT_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$ROOT_DIR"
start_component main_core "$ROOT_DIR/bin/main_core"
for _ in $(seq 1 50); do
  [[ -e "$SHM_PATH" ]] && break
  sleep 0.02
done
if [[ ! -e "$SHM_PATH" ]]; then
  echo "main_core did not create shared memory; see $LOG_DIR/main_core.log" >&2
  exit 1
fi
start_component main_control "$ROOT_DIR/bin/main_control"
start_component main_motor "$ROOT_DIR/bin/main_motor"
start_component main_sim "$ROOT_DIR/bin/main_sim"
start_component main_web_control "$ROOT_DIR/bin/main_web_control"
CONTROL_WEB_PID="$LAST_STARTED_PID"
start_component main_web_sim "$ROOT_DIR/bin/main_web_sim"
SIM_WEB_PID="$LAST_STARTED_PID"
sleep 0.5
if ! kill -0 "$CONTROL_WEB_PID" 2>/dev/null; then
  echo "main_web_control exited early; see $LOG_DIR/main_web_control.log" >&2
  cat "$LOG_DIR/main_web_control.log" >&2 || true
  exit 1
fi
if ! kill -0 "$SIM_WEB_PID" 2>/dev/null; then
  echo "main_web_sim exited early; see $LOG_DIR/main_web_sim.log" >&2
  cat "$LOG_DIR/main_web_sim.log" >&2 || true
fi
if command -v curl >/dev/null 2>&1; then
  if ! curl -fsS --max-time 2 "http://127.0.0.1:$WEB_PORT/control" >/dev/null; then
    echo "main_web_control /control check failed; see $LOG_DIR/main_web_control.log" >&2
    cat "$LOG_DIR/main_web_control.log" >&2 || true
    exit 1
  fi
  if ! curl -fsS --max-time 2 "http://127.0.0.1:$WEB_PORT/api/state" >/dev/null; then
    echo "main_web_control /api/state check failed; see $LOG_DIR/main_web_control.log" >&2
    cat "$LOG_DIR/main_web_control.log" >&2 || true
    exit 1
  fi
  curl -fsS --max-time 2 "http://127.0.0.1:$SIM_WEB_PORT/sim" >/dev/null || true
fi
echo "therapy robot simulation mode started on Jetson"
echo "entry point: ./scripts/run-jetson-sim.sh"
echo "control: http://<jetson-ip>:$WEB_PORT/control"
echo "sim:     http://<jetson-ip>:$SIM_WEB_PORT/sim"
echo "logs:    $LOG_DIR"
echo "runtime: $RUNTIME_DIR"
echo "collision config: $THERAPY_ROBOT_COLLISION_CONFIG required=$THERAPY_ROBOT_COLLISION_REQUIRED"
