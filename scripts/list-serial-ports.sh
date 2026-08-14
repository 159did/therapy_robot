#!/usr/bin/env bash
set -euo pipefail

SERIAL_DIR="${1:-/dev/serial/by-id}"

echo "Stable serial device paths:"
if [[ -d "$SERIAL_DIR" ]]; then
  ls -l "$SERIAL_DIR"
else
  echo "  $SERIAL_DIR not found"
fi

echo
echo "Current ttyUSB/ttyACM devices:"
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  none"
