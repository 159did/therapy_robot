#!/usr/bin/env python3
"""Software-only B2-A API and read-only invariant test."""

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
import urllib.error
import urllib.request
import uuid


READ_ONLY_ACTIONS = {
    "view_state",
    "view_self_check",
    "refresh_state",
    "preview_motion_plan",
}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3.0) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def wait_for(predicate, label: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
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


def state_snapshot(payload: dict) -> tuple:
    command = payload["command"]
    endpoint = payload["control"]["endpoint_target"]
    motors = tuple(
        (
            motor["configured"],
            motor["enabled"],
            motor["target_motor_native"],
            motor["active_target_motor_native"],
        )
        for group in payload["groups"]
        for motor in group["motors"]
    )
    return (
        command["command_seq"],
        command["target_command_seq"],
        tuple(command.get("target_native", [])),
        endpoint["target_seq"],
        motors,
    )


def runtime_signature(path: Path) -> tuple:
    if not path.exists():
        return ()
    return tuple(
        sorted(
            (str(item.relative_to(path)), item.stat().st_size, item.stat().st_mtime_ns)
            for item in path.rglob("*")
            if item.is_file()
        )
    )


def assert_common(payload: dict) -> None:
    assert payload["schema_version"] == "b2.v1"
    assert payload["ok"] is True
    assert payload["motor_command_written"] is False
    assert set(payload["source_state"]) == {
        "command_seq",
        "target_command_seq",
        "endpoint_target_seq",
    }
    for reason in payload["blocking_reasons"]:
        assert set(("code", "source", "severity", "message")) <= set(reason)
        assert reason["severity"] in {"info", "warning", "blocking"}


def run(main_core: Path, main_web: Path) -> None:
    repo = main_core.parents[2]
    token = f"b2_workflow_{os.getpid()}_{uuid.uuid4().hex[:10]}"
    shm_name = f"/therapy_robot_{token}"
    shm_path = Path("/dev/shm") / shm_name[1:]
    runtime = Path("/tmp") / token
    port = free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "THERAPY_ROBOT_SHM_NAME": shm_name,
            "THERAPY_ROBOT_RUNTIME_DIR": str(runtime),
            "THERAPY_ROBOT_WEB_PORT": str(port),
            "THERAPY_ROBOT_ROOT": str(repo),
            "THERAPY_ROBOT_COLLISION_REQUIRED": "1",
            "THERAPY_ROBOT_COLLISION_CONFIG": str(repo / "config/enclosure-collision.csv"),
        }
    )
    core = subprocess.Popen(
        [str(main_core)], cwd=repo, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    web: subprocess.Popen[str] | None = None
    try:
        wait_for(shm_path.exists, "isolated shared memory")
        web = subprocess.Popen(
            [str(main_web)], cwd=repo, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        def web_ready() -> bool:
            if web is None or web.poll() is not None:
                return True
            try:
                return get_json(port, "/api/workflow/state").get("schema_version") == "b2.v1"
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                return False

        wait_for(web_ready, "workflow API")
        if web.poll() is not None:
            stdout, stderr = web.communicate()
            raise AssertionError(f"web exited: stdout={stdout!r}, stderr={stderr!r}")

        before = get_json(port, "/api/state")
        before_state = state_snapshot(before)
        before_runtime = runtime_signature(runtime)

        state = get_json(port, "/api/workflow/state")
        assert_common(state)
        assert state["execution_locked"] is True
        assert state["workflow_state"] in {
            "offline", "fault", "locked", "storage", "standby",
            "vision_blocked", "ready_for_preview", "preview_blocked",
        }
        assert set(state["allowed_actions"]) <= READ_ONLY_ACTIONS
        assert state["plan_id"] is None and state["plan_hash"] is None

        self_check = get_json(port, "/api/workflow/self_check")
        assert_common(self_check)
        checks = {item["id"]: item for item in self_check["checks"]}
        assert checks["formal_camera_extrinsics"]["reason_code"] == "missing_formal_camera_extrinsics"
        assert checks["entity_offsets"]["reason_code"] == "entity_offsets_unverified"
        assert checks["automatic_execution_lock"]["status"] == "pass"
        assert self_check["self_check_summary"]["status"] == "blocked"

        paths = ["/api/workflow/state", "/api/workflow/self_check"] * 16
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda path: get_json(port, path), paths))
        for payload in responses:
            assert_common(payload)

        after = get_json(port, "/api/state")
        assert state_snapshot(after) == before_state, "B2-A GET endpoints changed shared command or motor state"
        assert runtime_signature(runtime) == before_runtime, "B2-A GET endpoints created or modified runtime files"
    finally:
        if web is not None:
            stop(web)
        stop(core)
        shm_path.unlink(missing_ok=True)
        shutil.rmtree(runtime, ignore_errors=True)

    print("PASS: B2-A workflow endpoints are fail-closed and read-only")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-core", required=True, type=Path)
    parser.add_argument("--main-web-control", required=True, type=Path)
    args = parser.parse_args()
    run(args.main_core.resolve(), args.main_web_control.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
