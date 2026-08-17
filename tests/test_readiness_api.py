#!/usr/bin/env python3
"""Software-only black-box test for the B3-A readiness GET."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3.0) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def wait_for(predicate, label: str) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    raise AssertionError(f"timed out waiting for {label}")


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.communicate(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=3.0)


def state_signature(payload: dict) -> tuple:
    command = payload["command"]
    endpoint = payload["control"]["endpoint_target"]
    motors = tuple(
        (motor["enabled"], motor["target_motor_native"], motor["active_target_motor_native"])
        for group in payload["groups"] for motor in group["motors"]
    )
    return (command["command_seq"], command["target_command_seq"], endpoint["target_seq"], motors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-core", required=True, type=Path)
    parser.add_argument("--main-web-control", required=True, type=Path)
    args = parser.parse_args()
    main_core = args.main_core.resolve()
    main_web = args.main_web_control.resolve()
    repo = main_core.parents[1]
    token = f"b3_readiness_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    shm_name = f"/therapy_robot_{token}"
    runtime = Path("/tmp") / token
    port = free_port()
    env = os.environ.copy()
    env.update({
        "THERAPY_ROBOT_SHM_NAME": shm_name,
        "THERAPY_ROBOT_RUNTIME_DIR": str(runtime),
        "THERAPY_ROBOT_WEB_PORT": str(port),
        "THERAPY_ROBOT_ROOT": str(repo),
        "THERAPY_ROBOT_COLLISION_REQUIRED": "1",
        "THERAPY_ROBOT_COLLISION_CONFIG": str(repo / "config/enclosure-collision.csv"),
    })
    core = subprocess.Popen([str(main_core)], cwd=repo, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    web = None
    shm_path = Path("/dev/shm") / shm_name[1:]
    try:
        wait_for(shm_path.exists, "isolated shared memory")
        web = subprocess.Popen([str(main_web)], cwd=repo, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        wait_for(lambda: get_json(port, "/api/readiness/attestation")["schema_version"] == "b3.v1",
                 "readiness API")
        before = state_signature(get_json(port, "/api/state"))
        first = get_json(port, "/api/readiness/attestation")
        assert first["schema_version"] == "b3.v1"
        for field in ("motor_command_written", "execution_allowed",
                      "entity_action_authorized", "nano_deployment_authorized"):
            assert first[field] is False
        assert first["authorization_scope"] == "software_precheck_only"
        assert first["expires_at_ms"] - first["issued_at_ms"] <= 300000
        assert len(first["attestation_id"]) > 10
        assert len(first["software_commit"]) == 40
        assert set(first["source_state"]) == {"command_seq", "target_command_seq", "endpoint_target_seq"}
        assert first["blocking_reasons"]
        responses = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: get_json(port, "/api/readiness/attestation"), range(32)))
        assert all(response["schema_version"] == "b3.v1" for response in responses)
        after = state_signature(get_json(port, "/api/state"))
        assert after == before, "readiness GET changed command, target, or motor state"
    finally:
        if web is not None:
            stop(web)
        stop(core)
        shm_path.unlink(missing_ok=True)
        shutil.rmtree(runtime, ignore_errors=True)
    print("PASS: B3-A readiness GET is fail-closed and read-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
