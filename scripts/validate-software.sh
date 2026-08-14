#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT_DIR/build/validation-host}"
RESULT_DIR="${RESULT_DIR:-$ROOT_DIR/build/validation-results/$(date +%Y%m%d-%H%M%S)-$$}"
BUILD_TYPE="${BUILD_TYPE:-RelWithDebInfo}"
JOBS="${JOBS:-$(nproc)}"
EMULATOR_PORT="${EMULATOR_PORT:-18080}"
EMULATOR_TIMEOUT_SEC="${EMULATOR_TIMEOUT_SEC:-240}"
EMULATOR_MODE="lock-only"

usage() {
  printf '%s\n' \
    "usage: $0 [--lock-only|--full-emulator|--skip-emulator]" \
    "          [--build-dir PATH] [--result-dir PATH] [--port PORT]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock-only) EMULATOR_MODE="lock-only" ;;
    --full-emulator) EMULATOR_MODE="full" ;;
    --skip-emulator) EMULATOR_MODE="skip" ;;
    --build-dir)
      shift
      [[ $# -gt 0 ]] || { usage >&2; exit 2; }
      BUILD_DIR="$1"
      ;;
    --result-dir)
      shift
      [[ $# -gt 0 ]] || { usage >&2; exit 2; }
      RESULT_DIR="$1"
      ;;
    --port)
      shift
      [[ $# -gt 0 ]] || { usage >&2; exit 2; }
      EMULATOR_PORT="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$BUILD_DIR" != /* || "$RESULT_DIR" != /* ]]; then
  echo "BUILD_DIR and RESULT_DIR must be absolute paths" >&2
  exit 2
fi
if [[ ! "$EMULATOR_PORT" =~ ^[0-9]+$ || ${#EMULATOR_PORT} -gt 5 ]]; then
  echo "invalid emulator port: expected an integer from 1 to 65535" >&2
  exit 2
fi
EMULATOR_PORT=$((10#$EMULATOR_PORT))
if (( EMULATOR_PORT < 1 || EMULATOR_PORT > 65535 )); then
  echo "invalid emulator port: expected an integer from 1 to 65535" >&2
  exit 2
fi

mkdir -p "$RESULT_DIR"
SUMMARY_FILE="$RESULT_DIR/summary.tsv"
METADATA_FILE="$RESULT_DIR/metadata.txt"
: > "$SUMMARY_FILE"

{
  echo "started_at=$(date --iso-8601=seconds)"
  echo "root=$ROOT_DIR"
  echo "build_dir=$BUILD_DIR"
  echo "result_dir=$RESULT_DIR"
  echo "build_type=$BUILD_TYPE"
  echo "jobs=$JOBS"
  echo "emulator_mode=$EMULATOR_MODE"
  echo "emulator_port=$EMULATOR_PORT"
  echo "git_commit=$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
} > "$METADATA_FILE"

record_stage() {
  printf '%s\t%s\n' "$1" "$2" >> "$SUMMARY_FILE"
}

run_stage() {
  local name="$1"
  shift
  echo "[validate] $name"
  "$@" 2>&1 | tee "$RESULT_DIR/$name.log"
  local rc=${PIPESTATUS[0]}
  record_stage "$name" "$rc"
  return "$rc"
}

finish() {
  local overall="$1"
  echo "finished_at=$(date --iso-8601=seconds)" >> "$METADATA_FILE"
  echo "overall=$overall" >> "$METADATA_FILE"
  (
    cd "$RESULT_DIR" || exit 1
    sha256sum metadata.txt summary.tsv ./*.log > MANIFEST_SHA256.txt
  )
  sha256sum "$RESULT_DIR/MANIFEST_SHA256.txt" | tee "$RESULT_DIR/MANIFEST_FILE_SHA256.txt"
  echo "validation results: $RESULT_DIR"
  return "$overall"
}

if [[ -e /dev/shm/therapy_robot_shared_state ]]; then
  echo "refusing validation while /dev/shm/therapy_robot_shared_state exists" | tee "$RESULT_DIR/preflight.log" >&2
  record_stage preflight 2
  finish 2
  exit $?
fi

if ! python3 - "$EMULATOR_PORT" > "$RESULT_DIR/port-preflight.log" 2>&1 <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", port))
print(f"port {port} is available")
PY
then
  cat "$RESULT_DIR/port-preflight.log" >&2
  record_stage port-preflight 2
  finish 2
  exit $?
fi
record_stage port-preflight 0

mapfile -t SHELL_FILES < <(find "$ROOT_DIR/scripts" -maxdepth 1 -type f -name '*.sh' | sort)
mapfile -t PYTHON_FILES < <(find "$ROOT_DIR/scripts" "$ROOT_DIR/tests" -maxdepth 1 -type f -name '*.py' | sort)

overall=0
run_stage shell-syntax bash -n "${SHELL_FILES[@]}" || overall=1
run_stage python-syntax python3 -m py_compile "${PYTHON_FILES[@]}" || overall=1

if ! run_stage configure cmake -S "$ROOT_DIR" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" -DBUILD_TESTING=ON; then
  finish 1
  exit $?
fi
if ! run_stage build cmake --build "$BUILD_DIR" --parallel "$JOBS"; then
  finish 1
  exit $?
fi
run_stage ctest ctest --test-dir "$BUILD_DIR" --output-on-failure || overall=1

if [[ "$EMULATOR_MODE" != "skip" ]]; then
  emulator_command=(
    timeout "$EMULATOR_TIMEOUT_SEC"
    env "THERAPY_ROBOT_RUNTIME_DIR=$RESULT_DIR/runtime"
    python3 "$ROOT_DIR/tests/test_hardware_emulator.py"
    --root "$ROOT_DIR"
    --build-dir "$BUILD_DIR"
    --port "$EMULATOR_PORT"
  )
  if [[ "$EMULATOR_MODE" == "lock-only" ]]; then
    emulator_command+=(--lock-only)
  fi
  run_stage hardware-emulator "${emulator_command[@]}" || overall=1
else
  record_stage hardware-emulator SKIPPED
fi

if [[ -e /dev/shm/therapy_robot_shared_state ]]; then
  echo "validation left the default shared-memory object behind" | tee "$RESULT_DIR/postflight.log" >&2
  rm -f -- /dev/shm/therapy_robot_shared_state
  record_stage postflight 1
  overall=1
else
  echo "default shared memory absent after validation" > "$RESULT_DIR/postflight.log"
  record_stage postflight 0
fi

finish "$overall"
exit $?
