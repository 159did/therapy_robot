#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARDWARE_CONFIG="${THERAPY_ROBOT_HARDWARE_CONFIG:-$ROOT_DIR/config/jetson-hardware.env}"
if [[ -f "$HARDWARE_CONFIG" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$HARDWARE_CONFIG"
  set +a
fi
LOG_DIR="${LOG_DIR:-/tmp/therapy_robot}"
ACTIVE_GROUPS="${THERAPY_ROBOT_ACTIVE_GROUPS:-all}"
if [[ "${THERAPY_ROBOT_VALIDATE_G1_ONLY:-0}" == "1" ]]; then
  ACTIVE_GROUPS="1"
fi

DEFAULT_SERIAL_BY_ID_DIR="/dev/serial/by-id"
G0_PORT="${THERAPY_ROBOT_G0_PORT:-${THERAPY_ROBOT_G0_PORT_BY_ID:-/dev/ttyUSB0}}"
G1_PORT="${THERAPY_ROBOT_G1_PORT:-${THERAPY_ROBOT_G1_PORT_BY_ID:-/dev/ttyUSB1}}"
G2_PORT="${THERAPY_ROBOT_G2_PORT:-${THERAPY_ROBOT_G2_PORT_BY_ID:-/dev/ttyUSB2}}"
MAX_SPEED_NATIVE="${THERAPY_ROBOT_MAX_SPEED_NATIVE:-600}"
AXIS_MAX_SPEED_NATIVE="${THERAPY_ROBOT_AXIS_MAX_SPEED_NATIVE:-}"
BRAKE_AXES="${THERAPY_ROBOT_BRAKE_AXES:-K0}"
BRAKE_COMMAND_RETRIES="${THERAPY_ROBOT_BRAKE_COMMAND_RETRIES:-3}"
BRAKE_RETRY_GAP_MS="${THERAPY_ROBOT_BRAKE_RETRY_GAP_MS:-50}"
G0_MOTOR_IDS="${THERAPY_ROBOT_G0_MOTOR_IDS:-1}"
G1_MOTOR_IDS="${THERAPY_ROBOT_G1_MOTOR_IDS:-1,2}"
G2_MOTOR_IDS="${THERAPY_ROBOT_G2_MOTOR_IDS:-1,2}"
AXIS_DIRECTIONS="${THERAPY_ROBOT_AXIS_DIRECTIONS:-1,1,1,1,1}"
AXIS_LIMIT_MARGIN_NATIVE="${THERAPY_ROBOT_AXIS_LIMIT_MARGIN_NATIVE:-}"
AXIS_OFFSETS_NATIVE="${THERAPY_ROBOT_AXIS_OFFSETS_NATIVE:-auto}"
AUTO_ZERO_ON_START="${THERAPY_ROBOT_AUTO_ZERO_ON_START:-1}"
SERIAL_TIMEOUT_MS="${THERAPY_ROBOT_SERIAL_TIMEOUT_MS:-80}"
WATCHDOG_MS="${THERAPY_ROBOT_WATCHDOG_MS:-1000}"
MAX_COMM_FAILURES="${THERAPY_ROBOT_MAX_COMM_FAILURES:-3}"
MAX_CURRENT_A="${THERAPY_ROBOT_MAX_CURRENT_A:-0}"
CURRENT_SCALE_A="${THERAPY_ROBOT_CURRENT_SCALE_A:-0.01}"
ALLOW_ZERO="${THERAPY_ROBOT_ALLOW_ZERO:-0}"
REQUIRE_ALL_PORTS="${THERAPY_ROBOT_REQUIRE_ALL_PORTS:-1}"
COLLISION_CONFIG="${THERAPY_ROBOT_COLLISION_CONFIG:-$ROOT_DIR/config/enclosure-collision.csv}"
COLLISION_REQUIRED="${THERAPY_ROBOT_COLLISION_REQUIRED:-0}"
export THERAPY_ROBOT_COLLISION_CONFIG="$COLLISION_CONFIG"
export THERAPY_ROBOT_COLLISION_REQUIRED="$COLLISION_REQUIRED"

MOTOR_POLL_MS="${THERAPY_ROBOT_MOTOR_POLL_MS:-${THERAPY_ROBOT_HARDWARE_POLL_MS:-}}"
MOTOR_POLL_COMMANDS="${THERAPY_ROBOT_MOTOR_POLL_COMMANDS:-${THERAPY_ROBOT_DEBUG_POLL:-}}"

if [[ "${THERAPY_ROBOT_G1_PORT:-}" == "" && ! -e "$G1_PORT" && -e /dev/ttyUSB0 ]]; then
  G1_PORT="/dev/ttyUSB0"
fi

resolve_port() {
  local value="$1"
  if [[ -L "$value" || -e "$value" ]]; then
    python3 - "$value" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
    return 0
  fi
  printf '%s\n' "$value"
}

require_port_exists() {
  local label="$1"
  local active="$2"
  local raw="$3"
  local resolved="$4"
  if [[ "$active" != "1" ]]; then
    return 0
  fi
  if [[ ! -e "$resolved" ]]; then
    echo "warning: $label port missing, bus disabled for this run: configured='$raw' resolved='$resolved'" >&2
    if [[ -d "$DEFAULT_SERIAL_BY_ID_DIR" ]]; then
      echo "Available stable serial paths under $DEFAULT_SERIAL_BY_ID_DIR:" >&2
      ls -l "$DEFAULT_SERIAL_BY_ID_DIR" >&2 || true
    else
      echo "$DEFAULT_SERIAL_BY_ID_DIR is not available on this Jetson." >&2
    fi
    MISSING_ACTIVE_PORT=1
  fi
}

G0_PORT_RESOLVED="$(resolve_port "$G0_PORT")"
G1_PORT_RESOLVED="$(resolve_port "$G1_PORT")"
G2_PORT_RESOLVED="$(resolve_port "$G2_PORT")"

mkdir -p "$LOG_DIR"
mkdir -p "$ROOT_DIR/data/backup"
"$ROOT_DIR/scripts/kill-robot.sh" || true
SHM_PATH="/dev/shm/therapy_robot_shared_state"
rm -f "$SHM_PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

MISSING_ACTIVE_PORT=0
require_port_exists G0 "$( [[ "$ACTIVE_GROUPS" == *0* || "$ACTIVE_GROUPS" == "all" || "$ACTIVE_GROUPS" == "ALL" || "$ACTIVE_GROUPS" == "*" ]] && echo 1 || echo 0 )" "$G0_PORT" "$G0_PORT_RESOLVED"
require_port_exists G1 "$( [[ "$ACTIVE_GROUPS" == *1* || "$ACTIVE_GROUPS" == "all" || "$ACTIVE_GROUPS" == "ALL" || "$ACTIVE_GROUPS" == "*" ]] && echo 1 || echo 0 )" "$G1_PORT" "$G1_PORT_RESOLVED"
require_port_exists G2 "$( [[ "$ACTIVE_GROUPS" == *2* || "$ACTIVE_GROUPS" == "all" || "$ACTIVE_GROUPS" == "ALL" || "$ACTIVE_GROUPS" == "*" ]] && echo 1 || echo 0 )" "$G2_PORT" "$G2_PORT_RESOLVED"
if [[ "$MISSING_ACTIVE_PORT" == "1" && "$REQUIRE_ALL_PORTS" == "1" ]]; then
  echo "one or more active RS485 ports are missing; hardware startup aborted" >&2
  exit 1
fi

for port in "$G0_PORT_RESOLVED" "$G1_PORT_RESOLVED" "$G2_PORT_RESOLVED"; do
  if [[ -e "$port" && "$port" == /dev/tty* ]]; then
    chmod a+rw "$port" 2>/dev/null || true
  fi
done

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
THERAPY_ROBOT_HARDWARE=1 \
THERAPY_ROBOT_G0_PORT="$G0_PORT_RESOLVED" \
THERAPY_ROBOT_G1_PORT="$G1_PORT_RESOLVED" \
THERAPY_ROBOT_G2_PORT="$G2_PORT_RESOLVED" \
THERAPY_ROBOT_ACTIVE_GROUPS="$ACTIVE_GROUPS" \
THERAPY_ROBOT_MAX_SPEED_NATIVE="$MAX_SPEED_NATIVE" \
THERAPY_ROBOT_AXIS_MAX_SPEED_NATIVE="$AXIS_MAX_SPEED_NATIVE" \
THERAPY_ROBOT_BRAKE_AXES="$BRAKE_AXES" \
THERAPY_ROBOT_BRAKE_COMMAND_RETRIES="$BRAKE_COMMAND_RETRIES" \
THERAPY_ROBOT_BRAKE_RETRY_GAP_MS="$BRAKE_RETRY_GAP_MS" \
THERAPY_ROBOT_G0_MOTOR_IDS="$G0_MOTOR_IDS" \
THERAPY_ROBOT_G1_MOTOR_IDS="$G1_MOTOR_IDS" \
THERAPY_ROBOT_G2_MOTOR_IDS="$G2_MOTOR_IDS" \
THERAPY_ROBOT_AXIS_DIRECTIONS="$AXIS_DIRECTIONS" \
THERAPY_ROBOT_AXIS_LIMIT_MARGIN_NATIVE="$AXIS_LIMIT_MARGIN_NATIVE" \
THERAPY_ROBOT_AXIS_OFFSETS_NATIVE="$AXIS_OFFSETS_NATIVE" \
THERAPY_ROBOT_AUTO_ZERO_ON_START="$AUTO_ZERO_ON_START" \
THERAPY_ROBOT_SERIAL_TIMEOUT_MS="$SERIAL_TIMEOUT_MS" \
THERAPY_ROBOT_WATCHDOG_MS="$WATCHDOG_MS" \
THERAPY_ROBOT_MAX_COMM_FAILURES="$MAX_COMM_FAILURES" \
THERAPY_ROBOT_MAX_CURRENT_A="$MAX_CURRENT_A" \
THERAPY_ROBOT_CURRENT_SCALE_A="$CURRENT_SCALE_A" \
THERAPY_ROBOT_ALLOW_ZERO="$ALLOW_ZERO" \
THERAPY_ROBOT_MOTOR_DEBUG="${THERAPY_ROBOT_MOTOR_DEBUG:-}" \
THERAPY_ROBOT_MOTOR_POLL_MS="$MOTOR_POLL_MS" \
THERAPY_ROBOT_MOTOR_POLL_COMMANDS="$MOTOR_POLL_COMMANDS" \
THERAPY_ROBOT_HARDWARE_POLL_MS="${THERAPY_ROBOT_HARDWARE_POLL_MS:-}" \
THERAPY_ROBOT_DEBUG_POLL="${THERAPY_ROBOT_DEBUG_POLL:-}" \
"$ROOT_DIR/bin/main_motor" > "$LOG_DIR/main_motor.log" 2>&1 &
MOTOR_PID=$!
sleep 0.5
if ! kill -0 "$MOTOR_PID" 2>/dev/null; then
  echo "main_motor failed during hardware initialization; see $LOG_DIR/main_motor.log" >&2
  "$ROOT_DIR/scripts/kill-robot.sh" || true
  exit 1
fi
"$ROOT_DIR/bin/main_sim" > "$LOG_DIR/main_sim.log" 2>&1 &
"$ROOT_DIR/bin/main_web_control" > "$LOG_DIR/main_web_control.log" 2>&1 &
"$ROOT_DIR/bin/main_web_sim" > "$LOG_DIR/main_web_sim.log" 2>&1 &

IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -z "${IP_ADDR:-}" ]]; then
  IP_ADDR="192.168.2.100"
fi

cat <<EOF
therapy robot hardware mode started

Directory:
  $ROOT_DIR

Hardware config:
  $HARDWARE_CONFIG

Entry point:
  ./scripts/run-jetson-hardware.sh

Ports:
  active_groups: $ACTIVE_GROUPS
  G0: $G0_PORT -> $G0_PORT_RESOLVED
  G1: $G1_PORT -> $G1_PORT_RESOLVED
  G2: $G2_PORT -> $G2_PORT_RESOLVED
  max_speed_native: $MAX_SPEED_NATIVE
  axis_max_speed_native: ${AXIS_MAX_SPEED_NATIVE:-global default}
  brake_axes: $BRAKE_AXES
  brake_command_retries: $BRAKE_COMMAND_RETRIES
  brake_retry_gap_ms: $BRAKE_RETRY_GAP_MS
  motor_ids: G0=$G0_MOTOR_IDS G1=$G1_MOTOR_IDS G2=$G2_MOTOR_IDS
  axis_directions: $AXIS_DIRECTIONS
  axis_limit_margin_native: ${AXIS_LIMIT_MARGIN_NATIVE:-global default}
  axis_offsets_native: $AXIS_OFFSETS_NATIVE
  auto_zero_on_start: $AUTO_ZERO_ON_START
  watchdog_ms: $WATCHDOG_MS
  allow_zero: $ALLOW_ZERO
  collision_config: $COLLISION_CONFIG
  collision_required: $COLLISION_REQUIRED

Motor polling:
  interval_ms: ${MOTOR_POLL_MS:-50}
  commands: ${MOTOR_POLL_COMMANDS:-all}

Logs:
  $LOG_DIR/main_motor.log
  $LOG_DIR/main_web_control.log
  $LOG_DIR/main_web_sim.log

Open GUI:
  control: http://$IP_ADDR:8080/control
  sim:     http://$IP_ADDR:8081/sim
EOF
