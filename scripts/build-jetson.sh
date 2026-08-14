#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT_DIR/build/jetson}"
TOOLCHAIN_FILE="${TOOLCHAIN_FILE:-$ROOT_DIR/toolchain/jetson_nano_aarch64.cmake}"
INSTALL_DIR="${INSTALL_DIR:-$ROOT_DIR/bin_aarch64-linux-gnu}"
DEFAULT_CROSS_TOOLCHAIN_DIR="/home/zzq/PTR/program/CrossCompliers/gcc-linaro-7.5.0-2019.12-x86_64_aarch64-linux-gnu"
CROSS_TOOLCHAIN_DIR="${CROSS_TOOLCHAIN_DIR:-$DEFAULT_CROSS_TOOLCHAIN_DIR}"

if [[ -d "$CROSS_TOOLCHAIN_DIR/bin" ]]; then
  export PATH="$CROSS_TOOLCHAIN_DIR/bin:$PATH"
fi

if ! command -v aarch64-linux-gnu-g++ >/dev/null 2>&1; then
  echo "aarch64-linux-gnu-g++ not found." >&2
  echo "Set CROSS_TOOLCHAIN_DIR to the Linaro aarch64 toolchain directory." >&2
  exit 1
fi

if [[ -d "$BUILD_DIR" ]]; then
  rm -rf "$BUILD_DIR"
fi

if ! df -Pk "$ROOT_DIR" | awk 'NR==2 { exit !($4 > 1048576) }'; then
  echo "Not enough free disk space under $(df -Pk "$ROOT_DIR" | awk 'NR==2 {print $6}'). Need at least 1 GB free." >&2
  exit 1
fi

echo "Using cross compiler: $(command -v aarch64-linux-gnu-g++)" >&2
aarch64-linux-gnu-g++ --version | head -n 1 >&2

cmake -S "$ROOT_DIR" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DBUILD_TESTING=OFF \
  -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
  -DCMAKE_C_COMPILER="$(command -v aarch64-linux-gnu-gcc)" \
  -DCMAKE_CXX_COMPILER="$(command -v aarch64-linux-gnu-g++)" \
  -DCMAKE_AR="$(command -v aarch64-linux-gnu-ar)" \
  -DCMAKE_RANLIB="$(command -v aarch64-linux-gnu-ranlib)" \
  -DCMAKE_LINKER="$(command -v aarch64-linux-gnu-ld)"

cmake --build "$BUILD_DIR" -j"$(nproc)"
rm -rf "$INSTALL_DIR"
cmake --install "$BUILD_DIR" --prefix "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/scripts"
cp \
  "$ROOT_DIR/scripts/run-host.sh" \
  "$ROOT_DIR/scripts/run-jetson-hardware.sh" \
  "$ROOT_DIR/scripts/run-jetson-sim.sh" \
  "$ROOT_DIR/scripts/kill-robot.sh" \
  "$ROOT_DIR/scripts/deploy-jetson.sh" \
  "$ROOT_DIR/scripts/build-jetson.sh" \
  "$ROOT_DIR/scripts/pack-jetson-runtime-libs.sh" \
  "$ROOT_DIR/scripts/switch-run-mode.sh" \
  "$ROOT_DIR/scripts/list-serial-ports.sh" \
  "$INSTALL_DIR/scripts/"
chmod +x "$INSTALL_DIR/scripts/"*.sh
cp \
  "$ROOT_DIR/scripts/test_single_axis.py" \
  "$ROOT_DIR/scripts/run_motion_test_sequence.py" \
  "$INSTALL_DIR/scripts/"
chmod +x \
  "$INSTALL_DIR/scripts/test_single_axis.py" \
  "$INSTALL_DIR/scripts/run_motion_test_sequence.py"
if [[ -d "$ROOT_DIR/config" ]]; then
  mkdir -p "$INSTALL_DIR/config"
  cp -a "$ROOT_DIR/config/." "$INSTALL_DIR/config/"
fi
CROSS_TOOLCHAIN_DIR="$CROSS_TOOLCHAIN_DIR" "$ROOT_DIR/scripts/pack-jetson-runtime-libs.sh"
