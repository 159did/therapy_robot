#!/usr/bin/env python3
"""Black-box G2 motion-plan API and read-only invariant checks."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(port: int, path: str, expected_status: int = 200) -> dict:
    try:
        response = urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=3.0
        )
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status == expected_status, (path, response.status)
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


def assert_common(payload: dict, ok: bool) -> None:
    assert payload["schema_version"] == "b2.v1"
    assert payload["ok"] is ok
    assert payload["motor_command_written"] is False
    assert set(payload["source_state"]) == {
        "command_seq", "target_command_seq", "endpoint_target_seq"
    }
    for reason in payload["blocking_reasons"]:
        assert {"code", "source", "severity", "message"} <= set(reason)
        assert reason["severity"] in {"info", "warning", "blocking"}


def assert_preview(payload: dict, side: str) -> None:
    assert_common(payload, True)
    assert re.fullmatch(r"b2-[0-9a-f]{16}", payload["plan_id"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", payload["plan_hash"])
    assert payload["plan_id"] == "b2-" + payload["plan_hash"][7:23]
    assert payload["preview_valid"] is False
    assert payload["execution_allowed"] is False
    plan = payload["plan"]
    assert plan["schema_version"] == "b2.motion-plan.v1"
    assert plan["side"] == side
    assert plan["coordinate_frame"] == "robot_base"
    assert plan["units"] == {"angular": "rad", "linear": "m"}
    assert plan["formal_use_allowed"] is False
    assert len(plan["segments"]) == 6
    for segment in plan["segments"]:
        assert {"segment_id", "phase", "start", "target", "preflight"} <= set(segment)
        assert {
            "ok", "collision_checked", "reason_code", "collision_link",
            "collision_obstacle", "path_fraction",
        } <= set(segment["preflight"])
    reason_codes = {item["code"] for item in payload["blocking_reasons"]}
    assert "synthetic_motion_plan_only" in reason_codes
    assert "missing_formal_camera_extrinsics" in reason_codes
    assert "entity_offsets_unverified" in reason_codes


def run(main_core: Path, main_web: Path) -> None:
    repo = main_core.parents[2]
    token = f"g2_motion_plan_{os.getpid()}_{uuid.uuid4().hex[:10]}"
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
            "THERAPY_ROBOT_COLLISION_CONFIG": str(
                repo / "config/enclosure-collision.csv"
            ),
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
                return get_json(port, "/api/motion_plan/preview?side=left").get(
                    "schema_version"
                ) == "b2.v1"
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                return False

        wait_for(web_ready, "motion plan API")
        if web.poll() is not None:
            stdout, stderr = web.communicate()
            raise AssertionError(f"web exited: stdout={stdout!r}, stderr={stderr!r}")

        before = state_snapshot(get_json(port, "/api/state"))
        before_runtime = runtime_signature(runtime)
        expected_source = {
            "command_seq": before[0],
            "target_command_seq": before[1],
            "endpoint_target_seq": before[3],
        }

        left = get_json(port, "/api/motion_plan/preview?side=left")
        right = get_json(port, "/api/motion_plan/preview?side=right")
        left_again = get_json(port, "/api/motion_plan/preview?side=left")
        assert_preview(left, "left")
        assert_preview(right, "right")
        assert all(item["source_state"] == expected_source for item in (left, right, left_again))
        assert left["plan_id"] == left_again["plan_id"]
        assert left["plan_hash"] == left_again["plan_hash"]
        assert left["plan"] == left_again["plan"]
        assert left["plan_id"] != right["plan_id"]
        assert left["plan_hash"] != right["plan_hash"]

        paths = [
            "/api/workflow/state",
            "/api/workflow/self_check",
            "/api/motion_plan/preview?side=left",
            "/api/motion_plan/preview?side=right",
        ] * 12
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda path: get_json(port, path), paths))
        for payload in responses:
            assert_common(payload, True)
            assert payload["source_state"] == expected_source

        for path in (
            "/api/motion_plan/preview",
            "/api/motion_plan/preview?side=center",
            "/api/motion_plan/preview?side=left&side=right",
        ):
            rejected = get_json(port, path, 400)
            assert_common(rejected, False)
            assert rejected["error_code"] == "invalid_motion_plan_side"
            assert rejected["source_state"] == expected_source

        after = state_snapshot(get_json(port, "/api/state"))
        assert after == before, "B2 GET endpoints changed command, target, or motor state"
        assert runtime_signature(runtime) == before_runtime, (
            "B2 GET endpoints created or modified runtime files"
        )
    finally:
        if web is not None:
            stop(web)
        stop(core)
        shm_path.unlink(missing_ok=True)
        shutil.rmtree(runtime, ignore_errors=True)

    print("PASS: G2 motion-plan API is deterministic, fail-closed, and read-only")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-core", required=True, type=Path)
    parser.add_argument("--main-web-control", required=True, type=Path)
    args = parser.parse_args()
    run(args.main_core.resolve(), args.main_web_control.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
