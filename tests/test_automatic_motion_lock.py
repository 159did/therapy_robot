#!/usr/bin/env python3
"""Verify every automatic-motion entry point is locked without actuation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.error
import uuid

import test_hardware_emulator as emulator


LOCK_ERROR_CODE = "automatic_trajectory_locked"
PID_FILES = ("motion_test_sequence.pid", "acupoint_sequence.pid")


def expect_http_lock(port: int, path: str, payload: dict) -> dict:
    try:
        emulator.request_json(port, path, payload)
        raise AssertionError(f"automatic motion entry point was not locked: {path}")
    except urllib.error.HTTPError as error:
        assert error.code == 409, f"unexpected status for {path}: {error.code}"
        result = json.loads(error.read().decode("utf-8"))
    assert result["ok"] is False
    assert result["execution_locked"] is True
    assert result["error_code"] == LOCK_ERROR_CODE
    assert result["motor_command_written"] is False
    assert result["motion_started"] is False
    return result


def pid_snapshot(runtime_dir: Path) -> dict[str, bytes | None]:
    return {
        name: (runtime_dir / name).read_bytes() if (runtime_dir / name).is_file() else None
        for name in PID_FILES
    }


def stable_state_snapshot(state: dict) -> dict:
    return {
        "command_seq": int(state["command"]["command_seq"]),
        "target_command_seq": int(state["command"]["target_command_seq"]),
        "endpoint_target_seq": int(state["control"]["endpoint_target"]["target_seq"]),
        "command": dict(state["command"]),
        "endpoint_target": dict(state["control"]["endpoint_target"]),
        "motors": emulator.motor_command_snapshot(state),
    }


def run_cli_lock(command: list[str], root: Path, environment: dict[str, str]) -> dict:
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert result.returncode == 2, (
        f"locked CLI returned {result.returncode}: stdout={result.stdout!r}, "
        f"stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["execution_locked"] is True
    assert payload["error_code"] == LOCK_ERROR_CODE
    assert payload["motor_command_written"] is False
    assert payload["motion_started"] is False
    return payload


def run(root: Path, build: Path, port: int) -> dict:
    binaries = [build / name for name in ("main_core", "main_control", "main_motor", "main_web_control")]
    for binary in binaries:
        if not binary.is_file():
            raise AssertionError(f"missing test binary: {binary}")

    token = f"b1_auto_lock_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    shared_memory_name = f"/therapy_robot_{token}"
    shared_memory_path = Path("/dev/shm") / shared_memory_name[1:]
    runtime_dir = Path(tempfile.gettempdir()) / f"therapy_robot_{token}"
    log_dir = Path(tempfile.mkdtemp(prefix="therapy-robot-auto-lock-"))
    buses = [emulator.BusEmulator((1,)), emulator.BusEmulator((1, 2)), emulator.BusEmulator((1, 2))]
    processes: list[subprocess.Popen[bytes]] = []

    if shared_memory_path.exists() or runtime_dir.exists():
        raise AssertionError("random test resources unexpectedly exist")
    for bus in buses:
        bus.start()

    base_environment = os.environ.copy()
    base_environment.update(
        {
            "THERAPY_ROBOT_SHM_NAME": shared_memory_name,
            "THERAPY_ROBOT_RUNTIME_DIR": str(runtime_dir),
            "THERAPY_ROBOT_COLLISION_REQUIRED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )

    def spawn(name: str, environment: dict[str, str]) -> None:
        log = (log_dir / f"{name}.log").open("wb")
        process = subprocess.Popen(
            [str(build / name)],
            cwd=root,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        processes.append(process)

    try:
        spawn("main_core", base_environment)
        emulator.wait_for(shared_memory_path.exists, "isolated shared memory")
        spawn("main_control", base_environment)

        hardware_environment = base_environment.copy()
        hardware_environment.update(
            {
                "THERAPY_ROBOT_HARDWARE": "1",
                "THERAPY_ROBOT_G0_PORT": buses[0].slave_path,
                "THERAPY_ROBOT_G1_PORT": buses[1].slave_path,
                "THERAPY_ROBOT_G2_PORT": buses[2].slave_path,
                "THERAPY_ROBOT_ACTIVE_GROUPS": "all",
                "THERAPY_ROBOT_AXIS_OFFSETS_NATIVE": "auto",
                "THERAPY_ROBOT_MOTOR_POLL_MS": "20",
                "THERAPY_ROBOT_SERIAL_TIMEOUT_MS": "200",
                "THERAPY_ROBOT_STATUS_EVERY_POLLS": "3",
                "THERAPY_ROBOT_WATCHDOG_MS": "2000",
                "THERAPY_ROBOT_ALLOW_ZERO": "1",
                "THERAPY_ROBOT_AXIS_OFFSETS_FILE": str(log_dir / "axis-offsets-native.txt"),
                "THERAPY_ROBOT_K0_POSITION_FILE": str(log_dir / "k0-last-logical-native.txt"),
                "THERAPY_ROBOT_MOTION_LOG_FILE": str(log_dir / "motor-motion-history.jsonl"),
                "THERAPY_ROBOT_MOTION_LOG_BACKUP_FILE": str(log_dir / "motor-motion-history.backup.jsonl"),
            }
        )
        initial_offsets = [
            buses[0].positions[1],
            buses[1].positions[1],
            buses[1].positions[2],
            buses[2].positions[1],
            buses[2].positions[2],
        ]
        (log_dir / "axis-offsets-native.txt").write_text(
            ",".join(str(value) for value in initial_offsets) + "\n",
            encoding="ascii",
        )
        spawn("main_motor", hardware_environment)

        web_environment = base_environment.copy()
        web_environment.update(
            {
                "THERAPY_ROBOT_ROOT": str(root),
                "THERAPY_ROBOT_WEB_PORT": str(port),
            }
        )
        spawn("main_web_control", web_environment)

        initial_state = emulator.wait_for(
            lambda: emulator.state_if(
                port,
                lambda state: state.get("system_state") == "hardware_ready",
            ),
            "hardware_ready",
        )
        time.sleep(0.25)
        state_before = stable_state_snapshot(emulator.request_json(port, "/api/state"))
        pids_before = pid_snapshot(runtime_dir)
        actuation_before = emulator.actuation_command_counts(buses)

        motion_lock = expect_http_lock(
            port,
            "/api/motion_test/sequence/start",
            {"side": "right"},
        )
        acupoint_lock = expect_http_lock(
            port,
            "/api/acupoint_sequence/start",
            {"names": "test-only"},
        )

        motion_status = emulator.request_json(port, "/api/motion_test/sequence/status")
        assert motion_status["execution_locked"] is True
        assert motion_status["error_code"] == LOCK_ERROR_CODE
        assert motion_status["motor_command_written"] is False
        assert motion_status["motion_started"] is False
        acupoint_status = emulator.request_json(port, "/api/acupoint_sequence/status")
        assert acupoint_status["ok"] is True
        assert acupoint_status["running"] is False
        simulation = emulator.request_json(port, "/api/motion_test/simulate", {"side": "right"})
        assert simulation["simulation_only"] is True
        assert simulation["motor_command_written"] is False

        cli_environment = web_environment.copy()
        motion_cli_lock = run_cli_lock(
            [
                "python3",
                str(root / "scripts/run_motion_test_sequence.py"),
                "--execute",
                "--base-url",
                f"http://127.0.0.1:{port}",
            ],
            root,
            cli_environment,
        )
        acupoint_cli_lock = run_cli_lock(
            [
                "python3",
                str(root / "scripts/run_acupoint_sequence.py"),
                "--execute",
                "--force",
                "--no-backend-check",
                "--result",
                "/nonexistent/automatic-motion-lock.json",
                "--base-url",
                f"http://127.0.0.1:{port}",
            ],
            root,
            cli_environment,
        )

        time.sleep(0.25)
        state_after = stable_state_snapshot(emulator.request_json(port, "/api/state"))
        pids_after = pid_snapshot(runtime_dir)
        actuation_after = emulator.actuation_command_counts(buses)

        assert state_after == state_before
        assert pids_after == pids_before
        assert actuation_after == actuation_before
        assert all(value is None for value in pids_after.values())

        return {
            "ok": True,
            "api_locks": {
                "motion_test": motion_lock["error_code"],
                "acupoint": acupoint_lock["error_code"],
            },
            "cli_locks": {
                "motion_test": motion_cli_lock["error_code"],
                "acupoint": acupoint_cli_lock["error_code"],
            },
            "command_seq_unchanged": True,
            "target_command_seq_unchanged": True,
            "endpoint_target_seq_unchanged": True,
            "motor_enable_and_targets_unchanged": True,
            "pid_files_unchanged": True,
            "actuation_commands_unchanged": True,
            "simulation_only_available": True,
            "actuation_commands_per_bus": actuation_after,
            "isolated_shared_memory": shared_memory_name,
            "isolated_runtime_dir": str(runtime_dir),
            "log_dir": str(log_dir),
            "initial_system_state": initial_state["system_state"],
        }
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 3.0
        for process in reversed(processes):
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        for bus in buses:
            bus.close()
        shared_memory_path.unlink(missing_ok=True)
        shutil.rmtree(runtime_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    result = run(args.root.resolve(), args.build_dir.resolve(), args.port)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
