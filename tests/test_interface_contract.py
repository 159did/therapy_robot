#!/usr/bin/env python3
"""Static, software-only checks for the frozen B0-B2 interface contract."""

import argparse
from pathlib import Path


def require(text: str, fragment: str, label: str) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {label}: {fragment}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    web = (root / "src/web/main_web.cpp").read_text(encoding="utf-8")
    shared_header = (root / "include/therapy_robot/shared_memory.hpp").read_text(encoding="utf-8")
    shared_cpp = (root / "src/common/shared_memory.cpp").read_text(encoding="utf-8")
    runtime_test = (root / "tests/test_runtime_isolation.py").read_text(encoding="utf-8")
    validation = (root / "scripts/validate-software.sh").read_text(encoding="utf-8")
    contract = (root / "docs/interface-contract.md").read_text(encoding="utf-8")

    lock_start = web.index('server.Post("/api/motion_test/sequence/start"')
    lock_end = web.index('server.Post("/api/motion_test/sequence/stop"', lock_start)
    lock_block = web[lock_start:lock_end]
    for field in (
        '\\"ok\\":false',
        '\\"execution_locked\\":true',
        '\\"error_code\\":\\"automatic_trajectory_locked\\"',
        '\\"motor_command_written\\":false',
        '\\"motion_started\\":false',
    ):
        require(lock_block, field, f"motion lock response field {field}")
    require(lock_block, "res.status = 409", "motion lock HTTP 409")
    require(web, 'server.Get("/api/motion_test/sequence/status"', "motion lock status endpoint")
    require(web, 'server.Post("/api/acupoint_sequence/start"', "acupoint endpoint owner boundary")

    require(shared_header, "kDefaultSharedMemoryName = \"/therapy_robot_shared_state\"", "default shared-memory name")
    require(shared_header, "const char* shared_memory_name();", "shared-memory name API")
    require(shared_cpp, 'std::getenv("THERAPY_ROBOT_SHM_NAME")', "shared-memory environment input")
    require(shared_cpp, "validate_shared_memory_name(name);", "shared-memory fail-closed validation")
    require(shared_cpp, "kMaxSharedMemoryNameLength = 255", "shared-memory length limit")

    require(web, 'std::getenv("THERAPY_ROBOT_RUNTIME_DIR")', "runtime directory input")
    require(web, 'const int port = current_web_port();', "strict Web port selection")
    require(web, 'configured_port("THERAPY_ROBOT_WEB_PORT", 8080)', "control port default")
    require(web, 'configured_port("THERAPY_ROBOT_SIM_WEB_PORT", 8081)', "simulation port default")
    assert '"/tmp/therapy_robot/' not in web, "Web source still contains a fixed runtime file path"

    require(runtime_test, "processes.pid", "runtime process registry test")
    require(runtime_test, "THERAPY_ROBOT_RUNTIME_DIR", "runtime isolation test environment")
    require(validation, "--full-emulator", "extended validation profile")
    require(validation, "hardware-emulator", "pseudo-hardware validation stage")
    require(validation, "overall", "validation summary return contract")

    for endpoint in (
        "GET /api/workflow/state",
        "GET /api/workflow/self_check",
        "GET /api/motion_plan/preview?side=left|right",
    ):
        require(contract, endpoint, f"B2 endpoint {endpoint}")
    for field in (
        '"schema_version": "b2.v1"',
        '"workflow_state"',
        '"allowed_actions"',
        '"blocking_reasons"',
        '"self_check_summary"',
        '"plan_id"',
        '"plan_hash"',
        '"motor_command_written": false',
        '"execution_allowed": false',
    ):
        require(contract, field, f"B2 stable contract field {field}")
    require(contract, "invalid_motion_plan_side", "B2 invalid side error code")
    require(contract, "b2.motion-plan.v1", "B2 motion plan schema version")
    require(contract, "sha256:", "B2 plan hash prefix")
    require(contract, "execution_allowed` is fixed false", "B2 execution hard lock")
    require(contract, "does not probe serial ports", "B2 passive self-check boundary")
    for forbidden in (
        "POST /api/workflow/state",
        "POST /api/workflow/self_check",
        "POST /api/motion_plan/preview",
    ):
        if forbidden in contract:
            raise AssertionError(f"B2 contract must not define a write endpoint: {forbidden}")

    print("PASS: B0-B2 interface contract assertions are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
