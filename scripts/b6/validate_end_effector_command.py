#!/usr/bin/env python3
"""Fail-closed validator for the B6 offline end-effector input contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "b6.end-effector-command.v1"
RESULT_SCHEMA = "b6.end-effector-validation-result.v1"
WORKSPACE_BOUNDS_M = {"x": (-0.60, 0.60), "y": (-0.60, 1.50), "z": (0.20, 1.80)}
MAX_SPEED_M_S = 0.05
MAX_ACCELERATION_M_S2 = 0.20
MAX_TIMEOUT_MS = 300_000
MIN_NON_CONTACT_OFFSET_M = 0.01
MAX_OFFSET_NORM_M = 0.20
ALLOWED_KEYS = {
    "schema_version", "command_id", "sequence", "created_at", "source", "idempotency_key",
    "coordinate_frame", "position_m", "orientation_policy", "target_kind", "executable",
    "max_speed", "max_acceleration", "max_jerk", "timeout_ms", "approach_offset_m",
    "retract_offset_m", "simulation_only", "formal_use_allowed", "promotion_locked", "execution_allowed",
    "entity_action_authorized", "nano_deployment_authorized", "h1_required", "feedback_required",
    "emergency_stop_required_clear", "collision_check_required", "status", "contract_sha256",
}
STATES = {"APPROACH", "HOLD", "RETRACT", "RETURN_HIGH", "STOPPED", "BLOCKED", "COMPLETE"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


class ContractError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def contract_hash(document: dict[str, Any]) -> str:
    unsigned = dict(document)
    unsigned.pop("contract_sha256", None)
    return hashlib.sha256(canonical(unsigned)).hexdigest()


def reject_nonfinite_constant(value: str) -> None:
    raise ContractError(f"non_finite_json_constant:{value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate_field:{key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonfinite_constant,
    )


def finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ContractError(f"{field}_must_be_finite")
    return float(value)


def vector(value: Any, field: str, *, nonzero: bool = False, max_norm: float | None = None) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ContractError(f"{field}_must_have_three_values")
    result = [finite(item, f"{field}[{index}]") for index, item in enumerate(value)]
    norm = math.sqrt(sum(item * item for item in result))
    if nonzero and norm < MIN_NON_CONTACT_OFFSET_M:
        raise ContractError(f"{field}_must_be_non_contact")
    if max_norm is not None and norm > max_norm:
        raise ContractError(f"{field}_exceeds_{max_norm}_m")
    return result


def parse_created_at(value: Any) -> None:
    if not isinstance(value, str) or not UTC_TIMESTAMP.fullmatch(value):
        raise ContractError("created_at_must_be_utc_iso8601")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError("created_at_invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise ContractError("created_at_must_be_utc")


def validate(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ContractError("document_must_be_object")
    unknown = set(document) - ALLOWED_KEYS
    missing = ALLOWED_KEYS - set(document)
    if unknown:
        raise ContractError("unknown_fields:" + ",".join(sorted(unknown)))
    if missing:
        raise ContractError("missing_fields:" + ",".join(sorted(missing)))
    if document["schema_version"] != SCHEMA:
        raise ContractError("schema_version_invalid")
    if not isinstance(document["command_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", document["command_id"]):
        raise ContractError("command_id_invalid")
    if not isinstance(document["sequence"], int) or isinstance(document["sequence"], bool) or document["sequence"] < 0:
        raise ContractError("sequence_invalid")
    parse_created_at(document["created_at"])
    if document["source"] not in {"offline_vision", "offline_demo", "simulation_review"}:
        raise ContractError("source_invalid")
    if not isinstance(document["idempotency_key"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", document["idempotency_key"]):
        raise ContractError("idempotency_key_invalid")
    if document["coordinate_frame"] not in {"robot_base", "robot_base_candidate"}:
        raise ContractError("coordinate_frame_invalid")
    position = vector(document["position_m"], "position_m")
    for axis, value in zip(("x", "y", "z"), position):
        lower, upper = WORKSPACE_BOUNDS_M[axis]
        if not lower <= value <= upper:
            raise ContractError(f"position_{axis}_outside_workspace")
    if document["orientation_policy"] not in {"keep_current", "tool_z_toward_target", "fixed_identity"}:
        raise ContractError("orientation_policy_invalid")
    if document["target_kind"] not in {"offline_simulation_only", "non_contact_preview"}:
        raise ContractError("target_kind_invalid")
    if document["coordinate_frame"] == "robot_base_candidate" and document["executable"] is not False:
        raise ContractError("candidate_coordinate_cannot_be_executable")
    if document["executable"] is not False:
        raise ContractError("executable_must_be_false")
    speed = document["max_speed"]
    acceleration = document["max_acceleration"]
    if not isinstance(speed, dict) or set(speed) != {"value", "unit"} or speed["unit"] != "m/s":
        raise ContractError("max_speed_unit_invalid")
    speed_value = finite(speed["value"], "max_speed")
    if speed_value <= 0:
        raise ContractError("max_speed_must_be_positive")
    if speed_value > MAX_SPEED_M_S:
        raise ContractError("max_speed_exceeds_experimental_limit")
    if not isinstance(acceleration, dict) or set(acceleration) != {"value", "unit"} or acceleration["unit"] != "m/s^2":
        raise ContractError("max_acceleration_unit_invalid")
    acceleration_value = finite(acceleration["value"], "max_acceleration")
    if acceleration_value <= 0:
        raise ContractError("max_acceleration_must_be_positive")
    if acceleration_value > MAX_ACCELERATION_M_S2:
        raise ContractError("max_acceleration_exceeds_experimental_limit")
    jerk = document["max_jerk"]
    if not isinstance(jerk, dict) or set(jerk) != {"supported", "value", "unit"} or jerk["supported"] is not False or jerk["value"] is not None or jerk["unit"] != "unsupported":
        raise ContractError("max_jerk_must_be_explicitly_unsupported")
    if not isinstance(document["timeout_ms"], int) or isinstance(document["timeout_ms"], bool) or not 1 <= document["timeout_ms"] <= MAX_TIMEOUT_MS:
        raise ContractError("timeout_ms_invalid")
    for field in ("approach_offset_m", "retract_offset_m"):
        offset = vector(document[field], field, nonzero=True, max_norm=MAX_OFFSET_NORM_M)
        endpoint = [position[index] + offset[index] for index in range(3)]
        for axis, value in zip(("x", "y", "z"), endpoint):
            lower, upper = WORKSPACE_BOUNDS_M[axis]
            if not lower <= value <= upper:
                raise ContractError(f"{field}_{axis}_endpoint_outside_workspace")
    fixed = {
        "simulation_only": True, "formal_use_allowed": False, "promotion_locked": True,
        "execution_allowed": False,
        "entity_action_authorized": False, "nano_deployment_authorized": False,
        "h1_required": True, "feedback_required": True,
        "emergency_stop_required_clear": True, "collision_check_required": True,
    }
    for field, expected in fixed.items():
        if document[field] is not expected:
            raise ContractError(f"{field}_must_be_{str(expected).lower()}")
    if document["status"] not in STATES:
        raise ContractError("status_invalid")
    declared = document["contract_sha256"]
    if not isinstance(declared, str) or not HEX64.fullmatch(declared):
        raise ContractError("contract_sha256_format_invalid")
    if declared != contract_hash(document):
        raise ContractError("contract_sha256_mismatch")
    return {
        "valid": True,
        "result_schema_version": RESULT_SCHEMA,
        "schema_version": SCHEMA,
        "command_id": document["command_id"],
        "sequence": document["sequence"],
        "status": document["status"],
        "coordinate_frame": document["coordinate_frame"],
        "position_m": position,
        "simulation_only": True,
        "formal_use_allowed": False,
        "promotion_locked": True,
        "executable": False,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "feedback_required": True,
        "emergency_stop_required_clear": True,
        "collision_check_required": True,
        "h1_required": True,
        "contract_sha256": declared,
        "motor_target_generated": False,
        "serial_payload_generated": False,
    }


def blocked(error: Exception) -> dict[str, Any]:
    return {
        "valid": False, "result_schema_version": RESULT_SCHEMA,
        "schema_version": SCHEMA, "blocking_reason": str(error),
        "simulation_only": True, "executable": False, "formal_use_allowed": False,
        "promotion_locked": True, "execution_allowed": False,
        "entity_action_authorized": False, "nano_deployment_authorized": False,
        "motor_target_generated": False,
        "serial_payload_generated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.out.resolve():
            raise ContractError("output_must_not_overwrite_input")
        report = validate(load_json(args.input))
    except (OSError, UnicodeError, json.JSONDecodeError, ContractError, TypeError, ValueError) as error:
        report = blocked(error)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
