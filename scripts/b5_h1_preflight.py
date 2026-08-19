#!/usr/bin/env python3
"""Read-only H1 software preflight; never opens serial/D405 or writes devices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def run(root: Path) -> dict:
    reasons: list[str] = []
    try:
        commit = _git(root, "rev-parse", "HEAD")
        clean = not bool(_git(root, "status", "--porcelain"))
    except (OSError, subprocess.CalledProcessError) as exc:
        commit, clean = "unknown", False
        reasons.append(f"git_unavailable:{type(exc).__name__}")
    if not clean:
        reasons.append("git_worktree_dirty")

    shm = Path("/dev/shm/therapy_robot_shared_state")
    if shm.exists():
        reasons.append("default_shared_memory_present")

    listeners: list[str] = []
    try:
        output = subprocess.check_output(["ss", "-ltnH"], text=True, stderr=subprocess.DEVNULL)
        listeners = [line.strip() for line in output.splitlines() if any(f":{port}" in line for port in ("8080", "8081"))]
    except (OSError, subprocess.CalledProcessError):
        reasons.append("listener_check_unavailable")
    if listeners:
        reasons.append("control_port_in_use")

    processes: list[str] = []
    try:
        output = subprocess.check_output(["ps", "-eo", "comm=,args="], text=True)
        processes = [line.strip() for line in output.splitlines() if any(name in line for name in ("main_core", "main_control", "main_motor", "main_web"))]
    except (OSError, subprocess.CalledProcessError):
        reasons.append("process_check_unavailable")
    if processes:
        reasons.append("robot_process_present")

    return {
        "schema_version": "b5.h1.preflight.v1",
        "checked_at_ms": int(time.time() * 1000),
        "software_commit": commit,
        "git_clean": clean,
        "default_shared_memory_present": shm.exists(),
        "control_listeners": listeners,
        "robot_processes": processes,
        "read_only": True,
        "entity_serial_accessed": False,
        "entity_d405_accessed": False,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "h1_window_authorized": False,
        "valid": not reasons,
        "blocking_reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.root.resolve())
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
