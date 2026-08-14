#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JETSON_HOST="${JETSON_HOST:-jetsonorin@192.168.2.100}"
JETSON_DIR="${JETSON_DIR:-/home/jetsonorin/Documents/therapy_robot}"
INSTALL_DIR="${INSTALL_DIR:-$ROOT_DIR/bin_aarch64-linux-gnu}"
STAGING_DIR="${JETSON_DIR}.uploading"
BACKUP_DIR="${JETSON_DIR}.previous"

"$ROOT_DIR/scripts/build-jetson.sh"

ssh "$JETSON_HOST" "rm -rf '$STAGING_DIR' && mkdir -p '$STAGING_DIR'"
scp -r "$INSTALL_DIR/." "$JETSON_HOST:$STAGING_DIR/"
ssh "$JETSON_HOST" "
  set -e
  mkdir -p '$STAGING_DIR/config'
  # Preserve operator calibration state across deployments.  The offset file
  # is intentionally not regenerated from build artifacts: it is the current
  # five-axis software zero selected on the real robot.
  for preserved_config in jetson-hardware.env enclosure-collision.csv axis-offsets-native.txt k0-last-logical-native.txt; do
    if [ -f '$JETSON_DIR/config/'\"\$preserved_config\" ]; then
      cp '$JETSON_DIR/config/'\"\$preserved_config\" '$STAGING_DIR/config/'\"\$preserved_config\"
    fi
  done
  if [ -d '$JETSON_DIR/data' ]; then
    mkdir -p '$STAGING_DIR/data'
    cp -a '$JETSON_DIR/data/.' '$STAGING_DIR/data/'
  fi
  if [ -x '$JETSON_DIR/scripts/kill-robot.sh' ]; then
    '$JETSON_DIR/scripts/kill-robot.sh' || true
  fi
  pkill -9 -f '[/]home/jetsonorin/Documents/therapy_robot/bin/main_' || true
  chmod +x '$STAGING_DIR/scripts/'*.sh '$STAGING_DIR/bin/'*
  rm -rf '$BACKUP_DIR'
  if [ -d '$JETSON_DIR' ]; then
    mv '$JETSON_DIR' '$BACKUP_DIR'
  fi
  mv '$STAGING_DIR' '$JETSON_DIR'
"
echo "deployed to $JETSON_HOST:$JETSON_DIR"
echo "Jetson hardware defaults use fixed physical by-path ports:"
echo "  G0 -> /dev/serial/by-path/platform-3610000.xhci-usb-0:2.1:1.0-port0"
echo "  G1 -> /dev/serial/by-path/platform-3610000.xhci-usb-0:2.2:1.0-port0"
echo "  G2 -> /dev/serial/by-path/platform-3610000.xhci-usb-0:2.3:1.0-port0"
echo "Run on Jetson with: ./scripts/run-jetson-hardware.sh"
