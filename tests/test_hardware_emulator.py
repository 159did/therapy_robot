#!/usr/bin/env python3
"""End-to-end MF9025V2 test using pseudo terminals, never real hardware."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


def checksum(data: bytes | bytearray) -> int:
    return sum(data) & 0xFF


class BusEmulator:
    def __init__(self, motor_ids: tuple[int, ...]) -> None:
        self.master_fd, slave_fd = pty.openpty()
        self.slave_path = os.ttyname(slave_fd)
        os.close(slave_fd)
        os.set_blocking(self.master_fd, False)
        self.motor_ids = motor_ids
        self.positions = {motor_id: 100000 + motor_id * 1000 for motor_id in motor_ids}
        self.enabled = {motor_id: False for motor_id in motor_ids}
        self.brake_engaged = {motor_id: True for motor_id in motor_ids}
        self.brake_operations: list[tuple[int, int]] = []
        self.commands: list[tuple[int, int]] = []
        self.motor_on_position_jump = 0
        self._buffer = bytearray()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        os.close(self.master_fd)

    def _write_response(self, command: int, motor_id: int, data: bytes = b"",
                        data_checksum: bool = False) -> None:
        header = bytearray((0x3E, command, motor_id, len(data)))
        header.append(checksum(header))
        frame = bytes(header) + data
        if data and data_checksum:
            frame += bytes((checksum(data),))
        os.write(self.master_fd, frame)

    def _status(self, motor_id: int) -> bytes:
        speed = 0
        current = 10 if self.enabled[motor_id] else 0
        encoder = self.positions[motor_id] & 0xFFFF
        return bytes((
            25,
            current & 0xFF, (current >> 8) & 0xFF,
            speed & 0xFF, (speed >> 8) & 0xFF,
            encoder & 0xFF, (encoder >> 8) & 0xFF,
        ))

    def _handle(self, frame: bytes) -> None:
        command = frame[1]
        motor_id = frame[2]
        length = frame[3]
        data = frame[5:5 + length]
        if motor_id not in self.positions:
            return
        self.commands.append((command, motor_id))

        if command == 0x88:
            self.positions[motor_id] += self.motor_on_position_jump
            self.enabled[motor_id] = True
            self._write_response(command, motor_id)
        elif command == 0x80:
            self.enabled[motor_id] = False
            self._write_response(command, motor_id)
        elif command == 0x81:
            self._write_response(command, motor_id)
        elif command == 0x92:
            self._write_response(
                command, motor_id,
                int(self.positions[motor_id]).to_bytes(8, "little", signed=True),
                data_checksum=True,
            )
        elif command == 0x9C:
            self._write_response(command, motor_id, self._status(motor_id), data_checksum=True)
        elif command in (0x9A, 0x9B):
            state = bytearray(7)
            state[5] = 1 if self.enabled[motor_id] else 0
            state[6] = 0
            self._write_response(command, motor_id, bytes(state), data_checksum=True)
        elif command == 0xA4:
            self.positions[motor_id] = int.from_bytes(data[:8], "little", signed=True)
            self._write_response(command, motor_id, self._status(motor_id), data_checksum=True)
        elif command == 0x8C:
            operation = data[0]
            self.brake_operations.append((motor_id, operation))
            if operation == 0x00:
                self.brake_engaged[motor_id] = True
            elif operation == 0x01:
                self.brake_engaged[motor_id] = False
            state = b"\x00" if self.brake_engaged[motor_id] else b"\x01"
            self._write_response(command, motor_id, state, data_checksum=True)
        elif command == 0x90:
            encoder = self.positions[motor_id] & 0xFFFFFFFF
            payload = bytes((data[0], 0, 0)) + encoder.to_bytes(4, "little")
            self._write_response(command, motor_id, payload, data_checksum=True)
        elif command == 0x94:
            single = self.positions[motor_id] % 36000
            self._write_response(command, motor_id,
                                 single.to_bytes(4, "little"), data_checksum=True)
        elif command == 0x95:
            self.positions[motor_id] = 0
            self._write_response(command, motor_id, bytes(7), data_checksum=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            readable, _, _ = select.select([self.master_fd], [], [], 0.05)
            if not readable:
                continue
            try:
                chunk = os.read(self.master_fd, 4096)
            except BlockingIOError:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                time.sleep(0.01)
                continue
            self._buffer.extend(chunk)
            while True:
                try:
                    start = self._buffer.index(0x3E)
                except ValueError:
                    self._buffer.clear()
                    break
                if start:
                    del self._buffer[:start]
                if len(self._buffer) < 5:
                    break
                length = self._buffer[3]
                frame_size = 5 + length + (1 if length else 0)
                if len(self._buffer) < frame_size:
                    break
                frame = bytes(self._buffer[:frame_size])
                del self._buffer[:frame_size]
                if checksum(frame[:4]) != frame[4]:
                    continue
                if length and checksum(frame[5:5 + length]) != frame[-1]:
                    continue
                self._handle(frame)


def request_json(port: int, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for(predicate, description: str, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {description}; last={last!r}")


def all_enabled(state: dict, expected: bool) -> bool:
    motors = [
        motor
        for group in state["groups"]
        for motor in group["motors"]
        if motor["configured"]
    ]
    return bool(motors) and all(bool(motor["enabled"]) is expected for motor in motors)


def actual_positions(state: dict) -> list[int]:
    return [
        int(state["groups"][0]["motors"][0]["actual_motor_native"]),
        int(state["groups"][1]["motors"][0]["actual_motor_native"]),
        int(state["groups"][1]["motors"][1]["actual_motor_native"]),
        int(state["groups"][2]["motors"][0]["actual_motor_native"]),
        int(state["groups"][2]["motors"][1]["actual_motor_native"]),
    ]


def state_if(port: int, predicate):
    value = request_json(port, "/api/state")
    return value if predicate(value) else None


ACTUATION_COMMANDS = frozenset((0x80, 0x81, 0x88, 0x8C, 0xA4))


def actuation_command_counts(buses: list[BusEmulator]) -> list[int]:
    return [
        sum(command in ACTUATION_COMMANDS for command, _motor_id in bus.commands)
        for bus in buses
    ]


def motor_command_snapshot(state: dict) -> list[dict]:
    return [
        {
            "axis": motor["axis"],
            "enabled": motor["enabled"],
            "target_motor_native": motor["target_motor_native"],
            "active_target_motor_native": motor["active_target_motor_native"],
        }
        for group in state["groups"]
        for motor in group["motors"]
        if motor["configured"]
    ]


def verify_motion_sequence_lock(port: int, buses: list[BusEmulator]) -> dict:
    state_before = request_json(port, "/api/state")
    command_before = dict(state_before["command"])
    endpoint_before = dict(state_before["control"]["endpoint_target"])
    motors_before = motor_command_snapshot(state_before)
    actuation_before = actuation_command_counts(buses)

    try:
        request_json(port, "/api/motion_test/sequence/start", {"side": "right"})
        raise AssertionError("complete automatic trajectory was not locked")
    except urllib.error.HTTPError as error:
        assert error.code == 409
        result = json.loads(error.read().decode("utf-8"))

    assert result["ok"] is False
    assert result["execution_locked"] is True
    assert result["error_code"] == "automatic_trajectory_locked"
    assert result["motor_command_written"] is False
    assert result["motion_started"] is False

    status = request_json(port, "/api/motion_test/sequence/status")
    assert status["execution_locked"] is True
    assert status["error_code"] == "automatic_trajectory_locked"
    assert status["motor_command_written"] is False
    assert status["motion_started"] is False

    simulation = request_json(port, "/api/motion_test/simulate", {"side": "right"})
    assert simulation["simulation_only"] is True
    assert simulation["motor_command_written"] is False

    time.sleep(0.25)
    state_after = request_json(port, "/api/state")
    assert state_after["command"] == command_before
    assert state_after["control"]["endpoint_target"] == endpoint_before
    assert motor_command_snapshot(state_after) == motors_before
    assert actuation_command_counts(buses) == actuation_before
    return {
        "http_status": 409,
        "error_code": result["error_code"],
        "command_state_unchanged": True,
        "motor_enable_and_targets_unchanged": True,
        "actuation_commands_unchanged": True,
        "simulation_only_available": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--lock-only", action="store_true",
        help="verify the automatic-trajectory lock, then stop before motion tests",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    build = Path(args.build_dir).resolve()
    binaries = [build / name for name in ("main_core", "main_control", "main_motor", "main_web_control")]
    for binary in binaries:
        if not binary.is_file():
            raise SystemExit(f"missing test binary: {binary}")

    buses = [BusEmulator((1,)), BusEmulator((1, 2)), BusEmulator((1, 2))]
    for bus in buses:
        bus.start()

    log_dir = Path(tempfile.mkdtemp(prefix="therapy-robot-emulator-"))
    processes: list[subprocess.Popen] = []
    shared_memory = Path("/dev/shm/therapy_robot_shared_state")
    shared_memory.unlink(missing_ok=True)

    def spawn(name: str, env: dict[str, str] | None = None) -> subprocess.Popen:
        log = (log_dir / f"{name}.log").open("wb")
        process = subprocess.Popen(
            [str(build / name)], cwd=root, env=env, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        processes.append(process)
        return process

    try:
        base_env = os.environ.copy()
        spawn("main_core", base_env)
        wait_for(shared_memory.exists, "shared memory")
        spawn("main_control", base_env)

        hardware_env = base_env.copy()
        hardware_env.update({
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
        })
        spawn("main_motor", hardware_env)

        web_env = base_env.copy()
        web_env["THERAPY_ROBOT_ROOT"] = str(root)
        web_env["THERAPY_ROBOT_WEB_PORT"] = str(args.port)
        spawn("main_web_control", web_env)

        state = wait_for(
            lambda: state_if(
                args.port, lambda value: value.get("system_state") == "hardware_ready"
            ),
            "hardware_ready",
        )
        assert actual_positions(state) == [0, 0, 0, 0, 0]
        assert state["run_mode"] == "hardware_relative"
        lock_result = verify_motion_sequence_lock(args.port, buses)
        if args.lock_only:
            print(json.dumps({
                "ok": True,
                "lock_verification": lock_result,
                "commands_per_bus": [len(bus.commands) for bus in buses],
                "log_dir": str(log_dir),
            }, ensure_ascii=False))
            return 0
        try:
            request_json(args.port, "/api/command/endpoint_target", {
                "x_m": 0.0, "y_m": 0.9, "z_m": 0.45,
                "rx_rad": 0.0, "ry_rad": 0.0, "rz_rad": 0.0,
            })
            raise AssertionError("relative hardware mode accepted an endpoint command")
        except urllib.error.HTTPError as error:
            assert error.code == 409

        try:
            request_json(args.port, "/api/command/jog_axis", {
                "axis": 4, "delta_display": 0.5,
            })
            raise AssertionError("disabled motors accepted a joint jog")
        except urllib.error.HTTPError as error:
            assert error.code == 409
        try:
            request_json(args.port, "/api/command/jog_axis_continuous", {
                "axis": 0, "direction": -1,
            })
            raise AssertionError("disabled motors accepted a continuous joint jog")
        except urllib.error.HTTPError as error:
            assert error.code == 409
        try:
            request_json(args.port, "/api/command/endpoint_jog", {
                "axis": "y", "delta_mm": -5,
            })
            raise AssertionError("disabled motors accepted an endpoint jog")
        except urllib.error.HTTPError as error:
            assert error.code == 409

        buses[0].motor_on_position_jump = 43200
        k0_commands_before_enable = len(buses[0].commands)
        k0_physical_before_enable = buses[0].positions[1]
        request_json(args.port, "/api/command/enable_all", {})
        wait_for(
            lambda: state_if(args.port, lambda value: all_enabled(value, True)),
            "all motors enabled",
        )
        k0_enable_commands = buses[0].commands[k0_commands_before_enable:]
        k0_enable_codes = [command for command, motor_id in k0_enable_commands
                           if motor_id == 1]
        assert 0x88 in k0_enable_codes
        assert 0xA4 in k0_enable_codes
        assert k0_enable_codes.index(0x88) < k0_enable_codes.index(0xA4)
        assert buses[0].positions[1] == k0_physical_before_enable + 43200
        assert buses[0].brake_engaged[1] is False

        try:
            request_json(args.port, "/api/command/endpoint_jog", {
                "axis": "y", "delta_mm": -5,
            })
            raise AssertionError("uncalibrated relative mode accepted an endpoint jog")
        except urllib.error.HTTPError as error:
            assert error.code == 409

        request_json(args.port, "/api/command/disable_all", {})
        wait_for(
            lambda: state_if(args.port, lambda value: all_enabled(value, False)),
            "motors disabled before software-zero capture",
        )
        request_json(args.port, "/api/command/set_zero", {})
        state = wait_for(
            lambda: state_if(args.port, lambda value: value.get("run_mode") == "hardware"),
            "persistent software-zero capture",
        )
        assert (log_dir / "axis-offsets-native.txt").exists()
        assert actual_positions(state) == [0, 0, 0, 0, 0]

        request_json(args.port, "/api/command/enable_all", {})
        wait_for(
            lambda: state_if(args.port, lambda value: all_enabled(value, True)),
            "all motors re-enabled after calibration",
        )

        request_json(args.port, "/api/command/targets", {
            "g0a0": 43200, "g1a0": 0, "g1a1": 0, "g2a0": 0, "g2a1": 0,
        })
        wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value) == [43200, 0, 0, 0, 0]),
            "K0 starts endpoint lift test at 3 mm safe clearance",
        )
        endpoint_lift = request_json(args.port, "/api/command/endpoint_jog", {
            "axis": "z", "delta_mm": 20,
        })
        assert endpoint_lift["target_pose"]["z"] > 496.0
        wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value)[0] == 331200),
            "Z+20 mm succeeds from K0 3 mm within expanded lift range",
        )
        request_json(args.port, "/api/command/targets", {
            "g0a0": 0, "g1a0": 0, "g1a1": 0, "g2a0": 0, "g2a1": 0,
        })
        wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value) == [0, 0, 0, 0, 0]),
            "axes reset after expanded lift endpoint test",
        )

        jog = request_json(args.port, "/api/command/jog_axis", {
            "axis": 4, "delta_display": 0.5,
        })
        assert jog["start_native"] == 0
        assert jog["target_native"] == 500
        wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value) == [0, 0, 0, 0, 500]),
            "K4 positive joint jog",
        )
        jog = request_json(args.port, "/api/command/jog_axis", {
            "axis": 4, "delta_display": -0.5,
        })
        assert jog["start_native"] == 500
        assert jog["target_native"] == 0
        wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value) == [0, 0, 0, 0, 0]),
            "K4 negative joint jog",
        )
        for body in ({"axis": 5, "delta_display": 0.5},
                     {"axis": 4, "delta_display": 10.1}):
            try:
                request_json(args.port, "/api/command/jog_axis", body)
                raise AssertionError(f"invalid joint jog accepted: {body}")
            except urllib.error.HTTPError as error:
                assert error.code == 400

        endpoint_jog = request_json(args.port, "/api/command/endpoint_jog", {
            "axis": "y", "delta_mm": 5,
        })
        assert endpoint_jog["command"] == "endpoint_jog"
        assert endpoint_jog["target_pose"]["y"] > 232.0
        moved_endpoint_state = wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value) != [0, 0, 0, 0, 0]),
            "relative endpoint jog reflected from emulated motors",
        )
        assert moved_endpoint_state["run_mode"] == "hardware"

        continuous = request_json(args.port, "/api/command/jog_axis_continuous", {
            "axis": 4, "direction": 1,
        })
        assert continuous["command"] == "jog_axis_continuous"
        assert continuous["target_native"] == 60000
        assert continuous["soft_limit_display"] == 60
        wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value)[4] == 60000),
            "K4 continuous jog reaches positive soft limit in emulator",
        )
        for body in ({"axis": 5, "direction": 1},
                     {"axis": 4, "direction": 0}):
            try:
                request_json(args.port, "/api/command/jog_axis_continuous", body)
                raise AssertionError(f"invalid continuous joint jog accepted: {body}")
            except urllib.error.HTTPError as error:
                assert error.code == 400

        targets = [100, 100, -100, 50, -50]
        request_json(args.port, "/api/command/targets", {
            "g0a0": targets[0], "g1a0": targets[1], "g1a1": targets[2],
            "g2a0": targets[3], "g2a1": targets[4],
        })
        state = wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value) == targets),
            "target positions reflected from emulated motors",
        )
        assert state["emergency_stop"] == 0

        arm_zero = request_json(args.port, "/api/command/return_arm_zero", {})
        assert arm_zero["command"] == "return_arm_zero"
        assert arm_zero["kept_k0"] is True
        state = wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value) == [100, 0, 0, 0, 0]),
            "K1-K4 return to zero while K0 is held",
        )

        z_zero = request_json(args.port, "/api/command/return_z_zero", {})
        assert z_zero["command"] == "return_z_zero"
        assert z_zero["target_k0_mm"] == 3
        assert z_zero["safe_clearance_mm"] == 3
        wait_for(
            lambda: state_if(args.port, lambda value: actual_positions(value) == [43200, 0, 0, 0, 0]),
            "K0 returns to its safe 3 mm clearance while K1-K4 are held",
        )

        request_json(args.port, "/api/command/stop_all", {})
        wait_for(lambda: buses[0].brake_engaged[1] is True,
                 "K0 brake engaged after stop")
        resumed_targets = [90, 100, -100, 50, -40]
        request_json(args.port, "/api/command/targets", {
            "g0a0": resumed_targets[0], "g1a0": resumed_targets[1],
            "g1a1": resumed_targets[2], "g2a0": resumed_targets[3],
            "g2a1": resumed_targets[4],
        })
        wait_for(lambda: buses[0].brake_engaged[1] is False,
                 "K0 brake released when position mode resumes")

        request_json(args.port, "/api/command/emergency_stop", {})
        state = wait_for(
            lambda: state_if(
                args.port,
                lambda value: value["emergency_stop"] == 1 and all_enabled(value, False),
            ),
            "emergency stop and motor off",
        )
        assert all(not enabled for bus in buses for enabled in bus.enabled.values())
        assert buses[0].brake_engaged[1] is True
        try:
            request_json(args.port, "/api/command/jog_axis", {
                "axis": 4, "delta_display": 0.5,
            })
            raise AssertionError("emergency stop accepted a joint jog")
        except urllib.error.HTTPError as error:
            assert error.code == 409
        k0_brake_operations = [
            operation for motor_id, operation in buses[0].brake_operations
            if motor_id == 1
        ]
        assert k0_brake_operations[:2] == [0x10, 0x10]
        assert 0x01 in k0_brake_operations
        assert 0x00 in k0_brake_operations
        assert k0_brake_operations[-1] == 0x00

        request_json(args.port, "/api/command/reset_emergency_stop", {})
        state = wait_for(
            lambda: state_if(args.port, lambda value: value["emergency_stop"] == 0),
            "emergency stop reset",
        )
        assert state["system_state"] == "hardware_ready"

        motion_log = log_dir / "motor-motion-history.jsonl"
        motion_backup = log_dir / "motor-motion-history.backup.jsonl"
        assert motion_log.exists() and motion_backup.exists()
        assert motion_log.read_bytes() == motion_backup.read_bytes()
        motion_events = [
            json.loads(line) for line in motion_log.read_text().splitlines()
            if line.strip()
        ]
        assert any(event["event"] == "command_start" for event in motion_events)
        assert any(event["event"] == "target_reached" for event in motion_events)
        assert {event["axis"] for event in motion_events} >= {"K0", "K1", "K2", "K3", "K4"}
        assert all("motor_turns_signed" in event for event in motion_events)
        assert all("actual_display" in event for event in motion_events)

        print(json.dumps({
            "ok": True,
            "positions": actual_positions(state),
            "commands_per_bus": [len(bus.commands) for bus in buses],
            "log_dir": str(log_dir),
        }, ensure_ascii=False))
        return 0
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
        for bus in buses:
            bus.close()
        shared_memory.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
