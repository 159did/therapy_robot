#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-/tmp/therapy_robot}"
SHM_PATH="/dev/shm/therapy_robot_shared_state"
export THERAPY_ROBOT_COLLISION_CONFIG="${THERAPY_ROBOT_COLLISION_CONFIG:-$ROOT_DIR/config/enclosure-collision.csv}"
export THERAPY_ROBOT_COLLISION_REQUIRED="${THERAPY_ROBOT_COLLISION_REQUIRED:-0}"
mkdir -p "$LOG_DIR"
"$ROOT_DIR/scripts/kill-robot.sh" || true
rm -f "$SHM_PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$ROOT_DIR"
"$ROOT_DIR/bin/main_core" > "$LOG_DIR/main_core.log" 2>&1 &
for _ in $(seq 1 50); do
  [[ -e "$SHM_PATH" ]] && break
  sleep 0.02
done
if [[ ! -e "$SHM_PATH" ]]; then
  echo "main_core did not create shared memory; see $LOG_DIR/main_core.log" >&2
  exit 1
fi
"$ROOT_DIR/bin/main_control" > "$LOG_DIR/main_control.log" 2>&1 &
"$ROOT_DIR/bin/main_motor" > "$LOG_DIR/main_motor.log" 2>&1 &
"$ROOT_DIR/bin/main_sim" > "$LOG_DIR/main_sim.log" 2>&1 &
"$ROOT_DIR/bin/main_web_control" > "$LOG_DIR/main_web_control.log" 2>&1 &
CONTROL_WEB_PID=$!
"$ROOT_DIR/bin/main_web_sim" > "$LOG_DIR/main_web_sim.log" 2>&1 &
SIM_WEB_PID=$!
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
  if ! curl -fsS --max-time 2 http://127.0.0.1:8080/control >/dev/null; then
    echo "main_web_control /control check failed; see $LOG_DIR/main_web_control.log" >&2
    cat "$LOG_DIR/main_web_control.log" >&2 || true
    exit 1
  fi
  if ! curl -fsS --max-time 2 http://127.0.0.1:8080/api/state >/dev/null; then
    echo "main_web_control /api/state check failed; see $LOG_DIR/main_web_control.log" >&2
    cat "$LOG_DIR/main_web_control.log" >&2 || true
    exit 1
  fi
  curl -fsS --max-time 2 http://127.0.0.1:8081/sim >/dev/null || true
fi
echo "therapy robot simulation mode started on Jetson"
echo "entry point: ./scripts/run-jetson-sim.sh"
echo "control: http://<jetson-ip>:8080/control"
echo "sim:     http://<jetson-ip>:8081/sim"
echo "logs:    $LOG_DIR"
echo "collision config: $THERAPY_ROBOT_COLLISION_CONFIG required=$THERAPY_ROBOT_COLLISION_REQUIRED"
