#!/usr/bin/env python3
"""Validate an S3 entity repeatability test snapshot without executing motion.

The input is a manually collected, read-only state snapshot. This tool never
connects to a device, starts a process, writes shared memory, or emits a motor
target/command. A successful result means only that the snapshot is complete
enough for a separate human review; it is not motion authorization.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "s3.endpoint-repeatability-preflight.v1"
S3_COMMIT = "2a974a3943e1946624c380fc9a535dff4aebde56"
REQUIRED_FIELDS = {
    "schema_version", "platform", "host", "software_commit", "nano_commit",
    "h1_status", "hardware_mode", "execution_allowed",
    "entity_action_authorized", "entity_motion_authorized", "feedback_valid",
    "feedback_age_ms", "feedback_max_age_ms", "watchdog_state", "limit_state",
    "collision_state", "brake_state_known", "brake_engaged", "estop_available",
    "workspace_clear", "operator_present", "estop_lead_present", "request_id",
    "authorization_id", "authorization_expiry_utc", "selected_points",
    "repetitions", "retreat_radius_m", "simulation_only", "nano_tested",
    "arm64_tested", "entity_hardware_tested", "serial_accessed", "d405_accessed",
    "motor_command_generated", "motor_target_generated", "serial_payload_generated",
    "shared_memory_written",
}
FALSE_OUTPUT_FIELDS = (
    "motor_command_generated", "motor_target_generated", "serial_payload_generated",
    "shared_memory_written",
)


class PreflightError(ValueError):
    pass


def finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PreflightError(f"{field}_must_be_finite")
    return float(value)


def require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise PreflightError(f"{field}_must_be_boolean")
    return value


def validate_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreflightError("snapshot_must_be_object")
    unknown = set(value) - REQUIRED_FIELDS
    missing = REQUIRED_FIELDS - set(value)
    if unknown:
        raise PreflightError("unknown_fields:" + ",".join(sorted(unknown)))
    if missing:
        raise PreflightError("missing_fields:" + ",".join(sorted(missing)))
    if value["schema_version"] != SCHEMA_VERSION:
        raise PreflightError("schema_version_invalid")
    for field in ("platform", "host", "software_commit", "nano_commit", "h1_status", "hardware_mode", "watchdog_state", "limit_state", "collision_state", "request_id", "authorization_id", "authorization_expiry_utc"):
        if not isinstance(value[field], str) or not value[field]:
            raise PreflightError(f"{field}_must_be_non_empty_string")
    if value["platform"] != "aarch64_nano":
        raise PreflightError("platform_must_be_aarch64_nano")
    if value["software_commit"] != S3_COMMIT:
        raise PreflightError("software_commit_mismatch")
    if value["h1_status"] != "H1_ENTITY_READONLY_PASS":
        raise PreflightError("h1_status_not_entity_readonly_pass")
    if value["hardware_mode"] != "HARDWARE_CONTROL":
        raise PreflightError("hardware_mode_not_explicit")
    for field in ("execution_allowed", "entity_action_authorized", "entity_motion_authorized", "simulation_only", "nano_tested", "arm64_tested", "entity_hardware_tested", "serial_accessed", "d405_accessed", *FALSE_OUTPUT_FIELDS):
        require_bool(value[field], field)
    for field in ("execution_allowed", "entity_action_authorized", "entity_motion_authorized"):
        if not value[field]:
            raise PreflightError(f"{field}_must_be_true_for_snapshot")
    if value["simulation_only"]:
        raise PreflightError("simulation_only_must_be_false_for_entity_snapshot")
    if not value["nano_tested"] or not value["arm64_tested"] or not value["entity_hardware_tested"]:
        raise PreflightError("hardware_evidence_flags_incomplete")
    if value["serial_accessed"] or value["d405_accessed"]:
        raise PreflightError("snapshot_must_not_claim_disallowed_device_access")
    if any(value[field] for field in FALSE_OUTPUT_FIELDS):
        raise PreflightError("entity_output_field_must_remain_false")
    for field in ("feedback_valid", "brake_state_known", "brake_engaged", "estop_available", "workspace_clear", "operator_present", "estop_lead_present"):
        require_bool(value[field], field)
    if not value["feedback_valid"]:
        raise PreflightError("feedback_invalid")
    finite(value["feedback_age_ms"], "feedback_age_ms")
    max_age = finite(value["feedback_max_age_ms"], "feedback_max_age_ms")
    if value["feedback_age_ms"] < 0 or max_age <= 0:
        raise PreflightError("feedback_age_range_invalid")
    if value["feedback_age_ms"] > max_age:
        raise PreflightError("feedback_expired")
    if value["watchdog_state"] != "OK":
        raise PreflightError("watchdog_timeout")
    if value["limit_state"] != "CLEAR":
        raise PreflightError("soft_limit_abnormal")
    if value["collision_state"] != "CLEAR":
        raise PreflightError("collision_abnormal")
    if not value["brake_state_known"]:
        raise PreflightError("brake_state_unknown")
    if not value["brake_engaged"]:
        raise PreflightError("brake_must_be_engaged_before_review")
    if not value["estop_available"]:
        raise PreflightError("emergency_stop_unavailable")
    for field in ("workspace_clear", "operator_present", "estop_lead_present"):
        if not value[field]:
            raise PreflightError(f"{field}_required")
    if not re.fullmatch(r"s3-[A-Za-z0-9_.:-]{8,128}", value["request_id"]):
        raise PreflightError("request_id_invalid")
    if not re.fullmatch(r"auth-[A-Za-z0-9_.:-]{8,128}", value["authorization_id"]):
        raise PreflightError("authorization_id_invalid")
    if not isinstance(value["selected_points"], int) or isinstance(value["selected_points"], bool) or not 1 <= value["selected_points"] <= 100:
        raise PreflightError("selected_points_out_of_range")
    if not isinstance(value["repetitions"], int) or isinstance(value["repetitions"], bool) or not 1 <= value["repetitions"] <= 100:
        raise PreflightError("repetitions_out_of_range")
    radius = finite(value["retreat_radius_m"], "retreat_radius_m")
    if not math.isclose(radius, 0.015, rel_tol=0.0, abs_tol=1e-12):
        raise PreflightError("retreat_radius_m_must_be_0.015")
    return value


def build_report(value: dict[str, Any]) -> dict[str, Any]:
    # A passing snapshot is only a handoff to a separately approved manual
    # review. This report never changes the execution permissions.
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_FOR_MANUAL_REVIEW",
        "go": False,
        "motion_authorized": False,
        "blocking_reasons": ["manual_review_and_specific_action_approval_required"],
        "platform": value["platform"],
        "host": value["host"],
        "software_commit": value["software_commit"],
        "nano_commit": value["nano_commit"],
        "h1_status": value["h1_status"],
        "simulation_only": value["simulation_only"],
        "nano_tested": value["nano_tested"],
        "arm64_tested": value["arm64_tested"],
        "entity_hardware_tested": value["entity_hardware_tested"],
        "selected_points": value["selected_points"],
        "repetitions": value["repetitions"],
        "retreat_radius_m": value["retreat_radius_m"],
        "execution_allowed": False,
        "entity_action_authorized": False,
        "entity_motion_authorized": False,
        "motor_command_generated": False,
        "motor_target_generated": False,
        "serial_payload_generated": False,
        "shared_memory_written": False,
        "serial_accessed": False,
        "d405_accessed": False,
    }


def blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "NO_GO",
        "go": False,
        "motion_authorized": False,
        "blocking_reasons": [reason],
        "platform": "unknown",
        "execution_allowed": False,
        "entity_action_authorized": False,
        "entity_motion_authorized": False,
        "motor_command_generated": False,
        "motor_target_generated": False,
        "serial_payload_generated": False,
        "shared_memory_written": False,
        "serial_accessed": False,
        "d405_accessed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.snapshot.resolve() == args.out.resolve():
            raise PreflightError("output_must_not_overwrite_snapshot")
        value = json.loads(args.snapshot.read_text(encoding="utf-8"), parse_constant=lambda item: (_ for _ in ()).throw(PreflightError(f"non_finite_json_constant:{item}")))
        report = build_report(validate_snapshot(value))
    except (OSError, UnicodeError, json.JSONDecodeError, PreflightError, TypeError, ValueError) as error:
        report = blocked(str(error))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "READY_FOR_MANUAL_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
