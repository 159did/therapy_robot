#!/usr/bin/env python3
"""Verify the automatic-execution lock contract and its fail-closed frontend.

Static checks run by default.  Live checks require --live and must target an
isolated software-simulation web instance; they never run against Nano.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request


LOCK_FIELDS = {
    "ok": False,
    "execution_locked": True,
    "error_code": "automatic_trajectory_locked",
    "motor_command_written": False,
    "motion_started": False,
}


def require(text: str, fragment: str, label: str) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {label}: {fragment}")


def block_between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def assert_lock_contract(payload: dict, label: str) -> None:
    for key, expected in LOCK_FIELDS.items():
        actual = payload.get(key)
        if actual != expected:
            raise AssertionError(f"{label}: {key}={actual!r}, expected {expected!r}: {payload!r}")


def static_checks(root: Path, frontend_only: bool = False) -> None:
    web_root = root / "web"
    html = (web_root / "control.html").read_text(encoding="utf-8")
    api = (web_root / "control/api.js").read_text(encoding="utf-8")
    main = (web_root / "control/main.js").read_text(encoding="utf-8")
    bindings = (web_root / "control/bindings.js").read_text(encoding="utf-8")
    active_entry = (web_root / "control_preview_20260810_v5.js").read_text(encoding="utf-8")
    active_main = (web_root / "control/main_preview_20260810_v5.js").read_text(encoding="utf-8")
    active_bindings = (web_root / "control/bindings_preview_20260810_v5.js").read_text(encoding="utf-8")
    backend = (root / "src/web/main_web.cpp").read_text(encoding="utf-8")

    require(html, 'src="/control_preview_20260810_v5.js"', "active control entry")
    require(active_entry, "./control/main_preview_20260810_v5.js", "active main module")
    require(html, 'id="startMotionTestSequence" class="secondary" disabled', "motion sequence disabled control")
    require(html, 'id="startSelectedAcupoints" disabled', "selected acupoints disabled control")
    require(html, 'id="startAcupointSequence" class="secondary" disabled', "all acupoints disabled control")

    require(api, "export class ApiError", "structured API error class")
    require(api, "this.errorCode", "structured API error code")
    require(api, "this.executionLocked", "structured API lock field")
    for module in (main, active_main):
        require(module, "status?.execution_locked !== false", "acupoint default lock")
        require(module, "catch(renderAcupointSequenceUnavailable)", "acupoint status fail-visible handling")
    for module in (bindings, active_bindings):
        require(module, "if (elements.startSelectedAcupoints.disabled) return;", "selected acupoint click guard")
        require(module, "if (elements.startAcupointSequence.disabled) return;", "all acupoint click guard")

    if frontend_only:
        print("PASS: frontend automatic-execution controls fail closed")
        return

    motion_start = block_between(
        backend,
        'server.Post("/api/motion_test/sequence/start"',
        'server.Post("/api/motion_test/sequence/stop"',
    )
    assert_lock_contract(
        {
            "ok": False,
            "execution_locked": True if r'\"execution_locked\":true' in motion_start else None,
            "error_code": "automatic_trajectory_locked" if "automatic_trajectory_locked" in motion_start else None,
            "motor_command_written": False if r'\"motor_command_written\":false' in motion_start else None,
            "motion_started": False if r'\"motion_started\":false' in motion_start else None,
        },
        "motion backend source",
    )
    require(motion_start, "res.status = 409", "motion lock HTTP 409")

    acupoint_start = block_between(
        backend,
        'server.Post("/api/acupoint_sequence/start"',
        'server.Post("/api/speed"',
    )
    # This intentionally fails until B1-A supplies the same backend lock.
    if "automatic_trajectory_locked" not in acupoint_start:
        raise AssertionError("acupoint backend start is not locked by automatic_trajectory_locked")
    require(acupoint_start, "res.status = 409", "acupoint lock HTTP 409")
    for field in LOCK_FIELDS:
        require(acupoint_start, f'\\"{field}\\"', f"acupoint lock field {field}")

    print("PASS: frontend fail-closed and automatic execution lock source checks")


def get_json(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base_url}{path}", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(base_url: str, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        return error.code, json.loads(body or "{}")


def command_snapshot(state: dict) -> tuple:
    command = state.get("command", {})
    endpoint = state.get("control", {}).get("endpoint_target", {})
    return (
        command.get("command_seq"),
        command.get("target_command_seq"),
        endpoint.get("target_seq"),
    )


def live_checks(base_url: str) -> None:
    before_state = get_json(base_url, "/api/state")
    if before_state.get("run_mode") != "sim" or before_state.get("simulation", {}).get("hardware_mode"):
        raise AssertionError("live lock test requires run_mode=sim and hardware_mode=0")
    for group in before_state.get("groups", []):
        for motor in group.get("motors", []):
            if motor.get("configured") and motor.get("enabled"):
                raise AssertionError("live lock test requires all simulated motors disabled")

    before_commands = command_snapshot(before_state)
    for path, label in (
        ("/api/motion_test/sequence/start", "motion test"),
        ("/api/acupoint_sequence/start", "acupoint sequence"),
    ):
        status, payload = post_json(base_url, path, {"side": "right"} if "motion_test" in path else {"names": ""})
        if status != 409:
            # A non-locked backend may have started a subprocess. Stop it before
            # failing so a bad contract cannot leave the isolated test running.
            if "acupoint_sequence" in path:
                post_json(base_url, "/api/acupoint_sequence/stop", {})
            raise AssertionError(f"{label} returned HTTP {status}, expected 409: {payload!r}")
        assert_lock_contract(payload, label)
        after_state = get_json(base_url, "/api/state")
        if command_snapshot(after_state) != before_commands:
            raise AssertionError(f"{label} changed command state: {before_commands!r} -> {command_snapshot(after_state)!r}")

    print("PASS: live motion and acupoint lock endpoints did not write commands")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    if args.frontend_only and args.live:
        parser.error("--frontend-only cannot be combined with --live")
    static_checks(args.root.resolve(), frontend_only=args.frontend_only)
    if args.live:
        live_checks(args.base_url.rstrip("/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
