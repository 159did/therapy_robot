#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT_DIR/build/host}"
LOG_DIR="${LOG_DIR:-/tmp/therapy_robot}"
SHM_NAME="${THERAPY_ROBOT_SHM_NAME-/therapy_robot_shared_state}"
if [[ ${#SHM_NAME} -gt 255 || "$SHM_NAME" == "/." || "$SHM_NAME" == "/.." || ! "$SHM_NAME" =~ ^/[A-Za-z0-9_.-]+$ ]]; then
  echo "invalid THERAPY_ROBOT_SHM_NAME: expected '/' followed by 1-254 safe characters" >&2
  exit 2
fi
SHM_PATH="/dev/shm/${SHM_NAME#/}"
export THERAPY_ROBOT_SHM_NAME="$SHM_NAME"
SIM_MAX_SPEED_NATIVE="${THERAPY_ROBOT_SIM_MAX_SPEED_NATIVE:-}"
SIM_POLL_MS="${THERAPY_ROBOT_SIM_POLL_MS:-10}"
SIM_K0_SPEED_MM_S="${THERAPY_ROBOT_SIM_K0_SPEED_MM_S:-30}"
SIM_ROT_SPEED_DEG_S="${THERAPY_ROBOT_SIM_ROT_SPEED_DEG_S:-24}"
SIM_SPEED_MULTIPLIER="${THERAPY_ROBOT_SIM_SPEED_MULTIPLIER:-0.5}"
export THERAPY_ROBOT_COLLISION_CONFIG="${THERAPY_ROBOT_COLLISION_CONFIG:-$ROOT_DIR/config/enclosure-collision.csv}"
export THERAPY_ROBOT_COLLISION_REQUIRED="${THERAPY_ROBOT_COLLISION_REQUIRED:-0}"

mkdir -p "$LOG_DIR"
printf '%s\n' "$SIM_SPEED_MULTIPLIER" > "$LOG_DIR/speed_multiplier"
"$ROOT_DIR/scripts/kill-robot.sh" || true
rm -f -- "$SHM_PATH"

cd "$ROOT_DIR"
"$BUILD_DIR/main_core" > "$LOG_DIR/main_core.log" 2>&1 &
for _ in $(seq 1 50); do
  [[ -e "$SHM_PATH" ]] && break
  sleep 0.02
done
if [[ ! -e "$SHM_PATH" ]]; then
  echo "main_core did not create shared memory; see $LOG_DIR/main_core.log" >&2
  exit 1
fi
"$BUILD_DIR/main_control" > "$LOG_DIR/main_control.log" 2>&1 &
if [[ -n "$SIM_MAX_SPEED_NATIVE" ]]; then
  THERAPY_ROBOT_SIM_MAX_SPEED_NATIVE="$SIM_MAX_SPEED_NATIVE" THERAPY_ROBOT_SIM_POLL_MS="$SIM_POLL_MS" THERAPY_ROBOT_SIM_K0_SPEED_MM_S="$SIM_K0_SPEED_MM_S" THERAPY_ROBOT_SIM_ROT_SPEED_DEG_S="$SIM_ROT_SPEED_DEG_S" "$BUILD_DIR/main_motor" > "$LOG_DIR/main_motor.log" 2>&1 &
else
  THERAPY_ROBOT_SIM_POLL_MS="$SIM_POLL_MS" THERAPY_ROBOT_SIM_K0_SPEED_MM_S="$SIM_K0_SPEED_MM_S" THERAPY_ROBOT_SIM_ROT_SPEED_DEG_S="$SIM_ROT_SPEED_DEG_S" "$BUILD_DIR/main_motor" > "$LOG_DIR/main_motor.log" 2>&1 &
fi
"$BUILD_DIR/main_sim" > "$LOG_DIR/main_sim.log" 2>&1 &
"$BUILD_DIR/main_web_control" > "$LOG_DIR/main_web_control.log" 2>&1 &
"$BUILD_DIR/main_web_sim" > "$LOG_DIR/main_web_sim.log" 2>&1 &

echo "therapy robot started; logs: $LOG_DIR"
echo "control: http://127.0.0.1:8080/control"
echo "sim:     http://127.0.0.1:8081/sim"
echo "simulation speed: k0_mm_s=$SIM_K0_SPEED_MM_S rot_deg_s=$SIM_ROT_SPEED_DEG_S multiplier=$SIM_SPEED_MULTIPLIER poll_ms=$SIM_POLL_MS native_override=${SIM_MAX_SPEED_NATIVE:-none}"
echo "collision config: $THERAPY_ROBOT_COLLISION_CONFIG required=$THERAPY_ROBOT_COLLISION_REQUIRED"
