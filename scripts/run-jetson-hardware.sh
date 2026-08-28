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
AXIS_OFFSETS_NATIVE="${THERAPY_ROBOT_AXIS_OFFSETS_NATIVE-}"
AXIS_OFFSETS_FILE="${THERAPY_ROBOT_AXIS_OFFSETS_FILE-}"
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
START_SIM="${THERAPY_ROBOT_START_SIM:-0}"
if [[ "$START_SIM" != "0" && "$START_SIM" != "1" ]]; then
  echo "invalid THERAPY_ROBOT_START_SIM: expected 0 or 1" >&2
  exit 2
fi

if [[ "$AXIS_OFFSETS_NATIVE" != "auto" ]]; then
  echo "THERAPY_ROBOT_AXIS_OFFSETS_NATIVE must be exactly 'auto'; inline hardware offsets are forbidden" >&2
  exit 2
fi
if [[ -z "$AXIS_OFFSETS_FILE" ]]; then
  echo "THERAPY_ROBOT_AXIS_OFFSETS_FILE must name a persistent offsets file" >&2
  exit 2
fi
python3 - "$AXIS_OFFSETS_FILE" <<'PY'
from pathlib import Path
import re
import stat
import sys

path = Path(sys.argv[1])
try:
    file_status = path.stat()
except OSError as exc:
    raise SystemExit(f"required axis offsets file is missing or inaccessible: {path}: {exc}")
if not stat.S_ISREG(file_status.st_mode):
    raise SystemExit(f"required axis offsets file is not a regular file: {path}")
try:
    content = path.read_bytes()
except OSError as exc:
    raise SystemExit(f"required axis offsets file is unreadable: {path}: {exc}")

content = content.strip()
if not content:
    raise SystemExit(f"required axis offsets file is empty: {path}")
tokens = content.split(b",")
if len(tokens) != 5:
    raise SystemExit(f"axis offsets file must contain exactly 5 integers: {path}")
minimum = -(1 << 63)
maximum = (1 << 63) - 1
for token in tokens:
    token = token.strip()
    if not token:
        raise SystemExit(f"axis offsets file contains an empty value: {path}")
    if re.fullmatch(rb"[+-]?[0-9]+", token) is None:
        raise SystemExit(f"axis offsets file contains an invalid integer: {path}")
    value = int(token, 10)
    if value < minimum or value > maximum:
        raise SystemExit(f"axis offsets file contains an out-of-range integer: {path}")
PY

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

mkdir -p "$LOG_DIR" "$RUNTIME_DIR"
mkdir -p "$ROOT_DIR/data/backup"
PID_FILE="$RUNTIME_DIR/processes.pid"
if [[ -f "$PID_FILE" ]]; then
  "$ROOT_DIR/scripts/kill-robot.sh"
  rm -f -- "$SHM_PATH"
elif [[ -e "$SHM_PATH" ]]; then
  echo "shared memory already exists without this runtime's process registry: $SHM_PATH" >&2
  exit 1
fi
: > "$PID_FILE"

STARTUP_COMPLETE=0
cleanup_partial_startup() {
  if [[ "$STARTUP_COMPLETE" == "0" ]]; then
    "$ROOT_DIR/scripts/kill-robot.sh" || true
    rm -f -- "$SHM_PATH"
  fi
}
trap cleanup_partial_startup EXIT

LAST_STARTED_PID=""
start_component() {
  local name="$1"
  shift
  "$@" > "$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  local start_time="0"
  if [[ -r "/proc/$pid/stat" ]]; then
    start_time="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
  fi
  [[ -n "$start_time" ]] || start_time="0"
  printf '%s %s %s\n' "$pid" "$start_time" "$name" >> "$PID_FILE"
  LAST_STARTED_PID="$pid"
}
if [[ "${THERAPY_ROBOT_USE_BUNDLED_LIBS:-0}" == "1" ]]; then
  export LD_LIBRARY_PATH="$ROOT_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
else
  unset LD_LIBRARY_PATH
fi

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
start_component main_motor env \
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
THERAPY_ROBOT_AXIS_OFFSETS_FILE="$AXIS_OFFSETS_FILE" \
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
"$ROOT_DIR/bin/main_motor"
MOTOR_PID="$LAST_STARTED_PID"
sleep 0.5
if ! kill -0 "$MOTOR_PID" 2>/dev/null; then
  echo "main_motor failed during hardware initialization; see $LOG_DIR/main_motor.log" >&2
  exit 1
fi
if [[ "$START_SIM" == "1" ]]; then
  start_component main_sim "$ROOT_DIR/bin/main_sim"
  start_component main_web_sim "$ROOT_DIR/bin/main_web_sim"
fi
start_component main_web_control "$ROOT_DIR/bin/main_web_control"

STARTUP_COMPLETE=1
trap - EXIT

IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -z "${IP_ADDR:-}" ]]; then
  IP_ADDR="192.168.2.100"
fi
if [[ "$START_SIM" == "1" ]]; then
  SIM_GUI="http://$IP_ADDR:$SIM_WEB_PORT/sim"
else
  SIM_GUI="disabled (set THERAPY_ROBOT_START_SIM=1 to enable)"
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
  axis_offsets_source: $AXIS_OFFSETS_FILE
  auto_zero_on_start: $AUTO_ZERO_ON_START
  watchdog_ms: $WATCHDOG_MS
  allow_zero: $ALLOW_ZERO
  collision_config: $COLLISION_CONFIG
  collision_required: $COLLISION_REQUIRED

Motor polling:
  interval_ms: ${MOTOR_POLL_MS:-50}
  commands: ${MOTOR_POLL_COMMANDS:-all}
  simulation_motor_started: $START_SIM

Logs:
  $LOG_DIR/main_motor.log
  $LOG_DIR/main_web_control.log
  $LOG_DIR/main_web_sim.log

Open GUI:
  control: http://$IP_ADDR:$WEB_PORT/control
  sim:     $SIM_GUI

Runtime:
  directory: $RUNTIME_DIR
  shared_memory: $SHM_NAME
  process_registry: $PID_FILE
EOF
