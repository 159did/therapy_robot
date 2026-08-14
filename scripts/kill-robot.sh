#!/usr/bin/env bash
set -euo pipefail

PATTERN='main_core|main_control|main_motor|main_web_control|main_web_sim|main_web|main_sim'

# main_motor handles SIGTERM by sending stop and motor-off commands before exit.
pkill -TERM -f "$PATTERN" 2>/dev/null || true

for _ in $(seq 1 50); do
  if ! pgrep -f "$PATTERN" >/dev/null 2>&1; then
    exit 0
  fi
  sleep 0.02
done

echo "warning: robot processes did not stop within 1 second; forcing termination" >&2
pkill -KILL -f "$PATTERN" 2>/dev/null || true
