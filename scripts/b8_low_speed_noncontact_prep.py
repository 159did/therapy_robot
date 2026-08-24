#!/usr/bin/env python3
"""Offline-only B8 low-speed/non-contact preparation and fault rehearsal.

This tool validates a future experiment protocol and simulates safety-gate
decisions. It never opens hardware, emits a motor command, or accepts a real
motion value. Entity parameters must remain explicit placeholders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "b8.low-speed-noncontact-prep.v1"
RESULT_SCHEMA_VERSION = "b8.low-speed-noncontact-result.v1"
PLACEHOLDER = "PLACEHOLDER_REQUIRES_APPROVAL"
PLATFORM = "x86_64_vm"
REQUIRED_KEYS = {
    "schema_version", "request_id", "platform", "simulation_only", "nano_tested",
    "arm64_tested", "entity_experiment", "hardware_authorized", "entity_motion_authorized",
    "h1_status", "b8_safety_gate_status", "software_commit", "nano_commit", "entity_device_identity",
    "roles", "preconditions", "future_entity_parameters",
    "single_step_policy", "stop_conditions", "recovery_policy", "rollback", "evidence", "experiment_conclusion",
    "source_sha256",
}
ROLE_KEYS = {"operator", "emergency_stop_lead", "independent_reviewer"}
BOOLEAN_LOCKS = {
    "simulation_only": True,
    "nano_tested": False,
    "arm64_tested": False,
    "hardware_authorized": False,
    "entity_motion_authorized": False,
}
REQUIRED_POLICY = {
    "single_axis_only": True,
    "single_discrete_action_only": True,
    "continuous_jog_forbidden": True,
    "automatic_sequence_forbidden": True,
    "complete_left_route_forbidden": True,
    "complete_right_route_forbidden": True,
    "acupoint_sequence_forbidden": True,
    "human_contact_forbidden": True,
    "dummy_contact_forbidden": True,
    "workspace_clear_required": True,
    "operator_present_required": True,
    "emergency_stop_lead_present_required": True,
    "safety_state_reread_before_each_step": True,
    "manual_confirmation_before_each_step": True,
    "record_after_each_step": True,
    "automatic_recovery_forbidden": True,
    "new_request_id_for_recovery": True,
}
REQUIRED_PRECONDITIONS = {
    "environment_identity_recorded",
    "h1_incomplete_acknowledged",
    "no_entity_execution_authorized",
    "offline_fixture_only",
    "physical_workspace_clear_rule_defined",
    "operator_and_estop_roles_required",
    "manual_step_confirmation_required",
    "post_step_record_required",
}
REQUIRED_STOP_CONDITIONS = {
    "feedback_loss", "feedback_expired", "watchdog_timeout", "soft_limit_abnormal",
    "collision_abnormal", "brake_unknown", "emergency_stop_unavailable", "any_anomaly",
}
REQUIRED_RECOVERY = {
    "no_automatic_recovery": True,
    "requires_new_request_id": True,
    "requires_new_authorization": True,
    "reinspect_all_gates": True,
}
# Protocol policy names may mention forbidden actions (for example
# ``continuous_jog_forbidden``); reject only fields that would carry a
# transport/native execution payload.
FORBIDDEN_KEYS = re.compile(r"(motor_target|joint_target|serial_payload|serial_frame|setpoint|payload|axis_angle|native|target_command)", re.I)


class B8Error(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(document: dict[str, Any]) -> str:
    unsigned = dict(document)
    unsigned.pop("source_sha256", None)
    return hashlib.sha256(canonical(unsigned)).hexdigest()


def finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise B8Error(f"{field}_must_be_finite")
    return float(value)


def walk_forbidden(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if FORBIDDEN_KEYS.search(str(key)):
                raise B8Error(f"forbidden_entity_output_field:{path}.{key}")
            walk_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_forbidden(child, f"{path}[{index}]")


def validate_protocol(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise B8Error("protocol_must_be_object")
    unknown = set(value) - REQUIRED_KEYS
    missing = REQUIRED_KEYS - set(value)
    if unknown:
        raise B8Error("unknown_fields:" + ",".join(sorted(unknown)))
    if missing:
        raise B8Error("missing_fields:" + ",".join(sorted(missing)))
    if value["schema_version"] != SCHEMA_VERSION:
        raise B8Error("schema_version_invalid")
    if not isinstance(value["request_id"], str) or not re.fullmatch(r"b8-[A-Za-z0-9_.:-]{8,128}", value["request_id"]):
        raise B8Error("request_id_invalid")
    if value["platform"] != PLATFORM:
        raise B8Error("platform_must_be_x86_64_vm")
    for field, expected in BOOLEAN_LOCKS.items():
        if value[field] is not expected:
            raise B8Error(f"{field}_must_be_{str(expected).lower()}")
    if value["entity_experiment"] != "not_run":
        raise B8Error("entity_experiment_must_be_not_run")
    if value["h1_status"] != "H1_EVIDENCE_INCOMPLETE":
        raise B8Error("h1_status_must_be_incomplete")
    if value["b8_safety_gate_status"] != "PREPARATION_ONLY":
        raise B8Error("b8_safety_gate_status_invalid")
    if value["software_commit"] != "9e0c4b925062b0a7c8fd2fa25fd985fe9798402b":
        raise B8Error("software_commit_must_match_b8_baseline")
    if value["nano_commit"] != PLACEHOLDER:
        raise B8Error("nano_commit_must_be_placeholder")
    identity = value["entity_device_identity"]
    if not isinstance(identity, dict) or set(identity) != {"nano_host", "device_model", "serial_path", "usb_vid", "usb_pid", "serial_number", "firmware_version"}:
        raise B8Error("entity_device_identity_schema_invalid")
    if any(item != PLACEHOLDER for item in identity.values()):
        raise B8Error("entity_device_identity_must_be_placeholders")
    roles = value["roles"]
    if not isinstance(roles, dict) or set(roles) != ROLE_KEYS:
        raise B8Error("roles_schema_invalid")
    for key in ROLE_KEYS:
        if not isinstance(roles[key], str) or not roles[key]:
            raise B8Error(f"role_{key}_must_be_named_or_placeholder")
    preconditions = value["preconditions"]
    if not isinstance(preconditions, dict) or set(preconditions) != REQUIRED_PRECONDITIONS:
        raise B8Error("preconditions_schema_invalid")
    if any(item is not True for item in preconditions.values()):
        raise B8Error("preconditions_must_be_true_for_protocol_only")
    params = value["future_entity_parameters"]
    if not isinstance(params, dict) or set(params) != {"axis", "direction", "speed", "displacement", "stop_distance_limit"}:
        raise B8Error("future_entity_parameters_schema_invalid")
    if any(item != PLACEHOLDER for item in params.values()):
        raise B8Error("future_entity_parameters_must_be_placeholders")
    policy = value["single_step_policy"]
    if not isinstance(policy, dict) or set(policy) != set(REQUIRED_POLICY):
        raise B8Error("single_step_policy_schema_invalid")
    for key, expected in REQUIRED_POLICY.items():
        if policy[key] is not expected:
            raise B8Error(f"policy_{key}_must_be_{str(expected).lower()}")
    stops = value["stop_conditions"]
    if not isinstance(stops, list) or set(stops) != REQUIRED_STOP_CONDITIONS:
        raise B8Error("stop_conditions_incomplete")
    recovery = value["recovery_policy"]
    if recovery != REQUIRED_RECOVERY:
        raise B8Error("recovery_policy_invalid")
    rollback = value["rollback"]
    if not isinstance(rollback, dict) or set(rollback) != {"on_no_go", "on_anomaly", "evidence_location"}:
        raise B8Error("rollback_schema_invalid")
    if not all(isinstance(item, str) and item for item in rollback.values()):
        raise B8Error("rollback_values_invalid")
    evidence = value["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {"raw_log_location", "raw_log_sha256", "recorded_at_utc"}:
        raise B8Error("evidence_schema_invalid")
    if evidence["raw_log_location"] != "docs/progress/evidence/B8-LOW-SPEED-NONCONTACT/":
        raise B8Error("raw_log_location_invalid")
    if evidence["raw_log_sha256"] != PLACEHOLDER or evidence["recorded_at_utc"] != PLACEHOLDER:
        raise B8Error("entity_evidence_values_must_be_placeholders")
    if value["experiment_conclusion"] != "NO_GO_PREPARATION_ONLY":
        raise B8Error("experiment_conclusion_invalid")
    source_hash = value["source_sha256"]
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise B8Error("source_sha256_format_invalid")
    walk_forbidden(value)
    if source_hash != digest(value):
        raise B8Error("source_sha256_mismatch")
    return value


def simulate_fault(scenario: str) -> dict[str, Any]:
    allowed = scenario == "nominal"
    if allowed:
        return {
            "scenario": scenario, "status": "PREPARED_OFFLINE", "go": False,
            "blocking_reasons": [
                "h1_entity_readonly_pass_required",
                "b8_safety_gate_integration_required",
                "real_nano_arm64_evidence_required",
                "nano_readonly_state_required",
                "user_specific_action_approval_required",
                "entity_roles_and_workspace_confirmation_required",
            ],
            "recovery_requires_new_request_id": True, "automatic_recovery": False,
        }
    mapping = {
        "emergency_stop": "emergency_stop_unavailable",
        "feedback_loss": "feedback_loss",
        "feedback_expired": "feedback_expired",
        "watchdog_timeout": "watchdog_timeout",
        "soft_limit_abnormal": "soft_limit_abnormal",
        "collision_abnormal": "collision_abnormal",
        "brake_unknown": "brake_unknown",
        "authorization_expired": "authorization_expired",
    }
    if scenario not in mapping:
        raise B8Error("scenario_invalid")
    return {
        "scenario": scenario, "status": "NO_GO", "go": False,
        "blocking_reasons": [mapping[scenario]], "stop_immediately": True,
        "automatic_recovery": False, "recovery_requires_new_request_id": True,
        "recovery_requires_new_authorization": True,
    }


def build_report(document: dict[str, Any], scenario: str) -> dict[str, Any]:
    result = simulate_fault(scenario)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "protocol_sha256": document["source_sha256"],
        "platform": PLATFORM,
        "simulation_only": True,
        "nano_tested": False,
        "arm64_tested": False,
        "entity_experiment": "not_run",
        "hardware_authorized": False,
        "entity_motion_authorized": False,
        "motor_command_generated": False,
        "native_setpoint_generated": False,
        "serial_payload_generated": False,
        **result,
    }


def blocked(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION, "platform": PLATFORM,
        "simulation_only": True, "nano_tested": False, "arm64_tested": False,
        "entity_experiment": "not_run", "hardware_authorized": False,
        "entity_motion_authorized": False, "motor_command_generated": False,
        "native_setpoint_generated": False, "serial_payload_generated": False,
        "status": "BLOCKED", "go": False, "blocking_reasons": [str(error)],
        "automatic_recovery": False, "recovery_requires_new_request_id": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--scenario", default="nominal")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.out.resolve():
            raise B8Error("output_must_not_overwrite_input")
        value = json.loads(args.input.read_text(encoding="utf-8"), parse_constant=lambda item: (_ for _ in ()).throw(B8Error(f"non_finite_json_constant:{item}")))
        report = build_report(validate_protocol(value), args.scenario)
    except (OSError, UnicodeError, json.JSONDecodeError, B8Error, TypeError, ValueError) as error:
        report = blocked(error)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PREPARED_OFFLINE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
