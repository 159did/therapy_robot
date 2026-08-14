#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$ROOT_DIR/bin_aarch64-linux-gnu}"
LIB_DIR="$INSTALL_DIR/lib"

rm -rf "$LIB_DIR"
mkdir -p "$LIB_DIR"

if [[ ! -d "$CROSS_TOOLCHAIN_DIR" ]]; then
  echo "CROSS_TOOLCHAIN_DIR is not set to a valid toolchain directory." >&2
  exit 1
fi

TOOLCHAIN_LIB_DIRS=(
  "$CROSS_TOOLCHAIN_DIR/aarch64-linux-gnu/libc/lib"
  "$CROSS_TOOLCHAIN_DIR/aarch64-linux-gnu/lib"
  "$CROSS_TOOLCHAIN_DIR/aarch64-linux-gnu/lib64"
  "$CROSS_TOOLCHAIN_DIR/lib/gcc/aarch64-linux-gnu/7.5.0"
)

RUNTIME_LIBS=(
  libstdc++.so.6
  libgcc_s.so.1
)

for soname in "${RUNTIME_LIBS[@]}"; do
  copied=0
  for search_dir in "${TOOLCHAIN_LIB_DIRS[@]}"; do
    if [[ -f "$search_dir/$soname" ]]; then
      cp -P "$search_dir/$soname" "$LIB_DIR/"
      copied=1
      break
    fi
  done
  if [[ "$copied" -ne 1 ]]; then
    echo "warning: runtime library not found in toolchain: $soname" >&2
  fi
done

echo "packed runtime libs into $LIB_DIR"
