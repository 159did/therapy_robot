#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT_DIR/build/host}"
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
SIM_MAX_SPEED_NATIVE="${THERAPY_ROBOT_SIM_MAX_SPEED_NATIVE:-}"
SIM_POLL_MS="${THERAPY_ROBOT_SIM_POLL_MS:-10}"
SIM_K0_SPEED_MM_S="${THERAPY_ROBOT_SIM_K0_SPEED_MM_S:-30}"
SIM_ROT_SPEED_DEG_S="${THERAPY_ROBOT_SIM_ROT_SPEED_DEG_S:-24}"
SIM_SPEED_MULTIPLIER="${THERAPY_ROBOT_SIM_SPEED_MULTIPLIER:-0.5}"
export THERAPY_ROBOT_COLLISION_CONFIG="${THERAPY_ROBOT_COLLISION_CONFIG:-$ROOT_DIR/config/enclosure-collision.csv}"
export THERAPY_ROBOT_COLLISION_REQUIRED="${THERAPY_ROBOT_COLLISION_REQUIRED:-0}"

mkdir -p "$LOG_DIR"
mkdir -p "$RUNTIME_DIR"
printf '%s\n' "$SIM_SPEED_MULTIPLIER" > "$RUNTIME_DIR/speed_multiplier"
"$ROOT_DIR/scripts/kill-robot.sh" || true
rm -f -- "$SHM_PATH"
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

cd "$ROOT_DIR"
start_component main_core "$BUILD_DIR/main_core"
for _ in $(seq 1 50); do
  [[ -e "$SHM_PATH" ]] && break
  sleep 0.02
done
if [[ ! -e "$SHM_PATH" ]]; then
  echo "main_core did not create shared memory; see $LOG_DIR/main_core.log" >&2
  exit 1
fi
start_component main_control "$BUILD_DIR/main_control"
if [[ -n "$SIM_MAX_SPEED_NATIVE" ]]; then
  start_component main_motor env THERAPY_ROBOT_SIM_MAX_SPEED_NATIVE="$SIM_MAX_SPEED_NATIVE" THERAPY_ROBOT_SIM_POLL_MS="$SIM_POLL_MS" THERAPY_ROBOT_SIM_K0_SPEED_MM_S="$SIM_K0_SPEED_MM_S" THERAPY_ROBOT_SIM_ROT_SPEED_DEG_S="$SIM_ROT_SPEED_DEG_S" "$BUILD_DIR/main_motor"
else
  start_component main_motor env THERAPY_ROBOT_SIM_POLL_MS="$SIM_POLL_MS" THERAPY_ROBOT_SIM_K0_SPEED_MM_S="$SIM_K0_SPEED_MM_S" THERAPY_ROBOT_SIM_ROT_SPEED_DEG_S="$SIM_ROT_SPEED_DEG_S" "$BUILD_DIR/main_motor"
fi
start_component main_sim "$BUILD_DIR/main_sim"
start_component main_web_control "$BUILD_DIR/main_web_control"
start_component main_web_sim "$BUILD_DIR/main_web_sim"

echo "therapy robot started; logs: $LOG_DIR"
echo "control: http://127.0.0.1:$WEB_PORT/control"
echo "sim:     http://127.0.0.1:$SIM_WEB_PORT/sim"
echo "runtime: $RUNTIME_DIR"
echo "simulation speed: k0_mm_s=$SIM_K0_SPEED_MM_S rot_deg_s=$SIM_ROT_SPEED_DEG_S multiplier=$SIM_SPEED_MULTIPLIER poll_ms=$SIM_POLL_MS native_override=${SIM_MAX_SPEED_NATIVE:-none}"
echo "collision config: $THERAPY_ROBOT_COLLISION_CONFIG required=$THERAPY_ROBOT_COLLISION_REQUIRED"
