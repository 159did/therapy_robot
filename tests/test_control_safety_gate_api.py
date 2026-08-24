#!/usr/bin/env python3
"""Black-box B8 API gate test using isolated x86_64 VM simulation state."""

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid


ENTITY_REQUESTS = {
    "/api/command/enable_all": {},
    "/api/command/disable_all": {},
    "/api/command/return_arm_zero": {},
    "/api/command/return_z_zero": {},
    "/api/command/set_zero": {},
    "/api/command/jog_axis": {"axis": 0, "delta_display": 1},
    "/api/command/jog_axis_continuous": {"axis": 0, "direction": 1},
    "/api/command/recovery_jog_axis": {"axis": 1, "delta_display": 1},
    "/api/command/endpoint_jog": {"axis": "x", "delta_mm": 1},
    "/api/command/endpoint_target": {
        "x_m": 0.1, "y_m": 0.2, "z_m": 0.3,
        "rx_rad": 0, "ry_rad": 0, "rz_rad": 0,
    },
    "/api/command/targets": {
        "g0a0": 0, "g1a0": 0, "g1a1": 0, "g2a0": 0, "g2a1": 0,
    },
    "/api/command/recover_arm_zero": {},
    "/api/acupoint_sequence/start": {},
    "/api/motion_test/sequence/start": {},
    "/api/mode/switch": {"mode": "hardware"},
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(port: int, method: str, path: str, body=None):
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=encoded, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_ready(port: int, process: subprocess.Popen, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"web process exited early: {process.returncode}")
        try:
            status, _ = request_json(port, "GET", "/api/state")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(0.05)
    raise AssertionError("isolated web service did not become ready")


def safety_projection(state):
    return {
        "command": copy.deepcopy(state["command"]),
        "control": copy.deepcopy(state["control"]),
        "groups": copy.deepcopy(state["groups"]),
        "emergency_stop": state["emergency_stop"],
    }


def run(main_core: Path, main_web: Path) -> None:
    root = main_core.parents[2]
    token = f"b8_gate_{os.getpid()}_{uuid.uuid4().hex[:10]}"
    shm_name = f"/therapy_robot_{token}"
    shm_path = Path("/dev/shm") / shm_name[1:]
    runtime = Path("/tmp") / f"therapy_robot_{token}"
    port = free_port()
    environment = os.environ.copy()
    environment.update({
        "THERAPY_ROBOT_SHM_NAME": shm_name,
        "THERAPY_ROBOT_RUNTIME_DIR": str(runtime),
        "THERAPY_ROBOT_WEB_PORT": str(port),
        "THERAPY_ROBOT_COLLISION_REQUIRED": "0",
        "THERAPY_ROBOT_ROOT": str(root),
    })
    core = subprocess.Popen([str(main_core)], cwd=root, env=environment)
    web = None
    try:
        deadline = time.monotonic() + 3
        while not shm_path.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert shm_path.exists(), "isolated shared memory was not created"
        web = subprocess.Popen([str(main_web)], cwd=root, env=environment)
        wait_ready(port, web)
        status, initial = request_json(port, "GET", "/api/state")
        assert status == 200
        initial_projection = safety_projection(initial)

        for path, payload in ENTITY_REQUESTS.items():
            status, result = request_json(port, "POST", path, payload)
            assert status == 403, (path, status, result)
            assert result["error"] == "control_safety_gate_rejected", (path, result)
            assert result["execution_allowed"] is False
            assert result["entity_action_authorized"] is False
            assert result["motor_command_generated"] is False
            assert result["motor_target_generated"] is False
            assert result["serial_payload_generated"] is False

        status, final = request_json(port, "GET", "/api/state")
        assert status == 200
        assert safety_projection(final) == initial_projection

        status, simulation = request_json(
            port, "POST", "/api/motion_test/simulate", {"side": "left"}
        )
        assert status == 200, simulation
        assert simulation["simulation_only"] is True
        assert simulation["execution_allowed"] is False
        assert simulation["entity_action_authorized"] is False
        assert simulation["motor_command_generated"] is False
        assert simulation["motor_target_generated"] is False
        assert simulation["serial_payload_generated"] is False

        print("platform=x86_64_vm host=zzqVM nano_tested=false "
              "arm64_tested=false entity_hardware_tested=false")
        print(f"entity_api_gate_passed={len(ENTITY_REQUESTS)}")
    finally:
        if web is not None and web.poll() is None:
            web.terminate()
            web.wait(timeout=3)
        if core.poll() is None:
            core.terminate()
            core.wait(timeout=3)
        shm_path.unlink(missing_ok=True)
        shutil.rmtree(runtime, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-core", type=Path, required=True)
    parser.add_argument("--main-web-control", type=Path, required=True)
    args = parser.parse_args()
    run(args.main_core.resolve(), args.main_web_control.resolve())
