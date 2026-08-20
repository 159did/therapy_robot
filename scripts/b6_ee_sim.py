#!/usr/bin/env python3
"""Deterministic offline simulator for a B6 end-effector command.

The program consumes a B6 contract command inside a simulation envelope and
emits state/trajectory facts only. It has no device, network, shared-memory,
deployment, or motor-command interface.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "b6.ee-sim-input.v1"
OUTPUT_SCHEMA = "b6.ee-sim.v1"
CONTRACT_SCHEMA = "b6.end-effector-command.v1"
TOOL_VERSION = "b6-ee-sim.1"
NORMAL_STATES = ("IDLE", "SAFE_HIGH", "APPROACH", "HOLD", "RETRACT", "RETURN_HIGH", "COMPLETE")
FAULTS = (
    "operator_stop",
    "emergency_stop",
    "watchdog_timeout",
    "feedback_loss",
    "feedback_stale",
    "collision_detected",
    "soft_limit_violation",
    "target_out_of_workspace",
)
WORKSPACE = ([-0.60, -0.60, 0.20], [0.60, 1.50, 1.80])
SOFT_LIMITS = ([-0.55, -0.55, 0.25], [0.55, 1.45, 1.75])
CHASSIS_BOX = ([-0.075, -0.100, -0.0125], [0.075, 0.650, 0.7475])
CHASSIS_MARGIN_M = 0.001
MIN_OFFSET_M = 0.01
MAX_OFFSET_M = 0.20
MAX_SPEED_M_S = 0.05
MAX_ACCELERATION_M_S2 = 0.20
MIN_SAFE_HIGH_Z_M = 1.50
ENVELOPE_KEYS = {
    "schema_version", "synthetic", "side", "scenario", "command",
    "start_position_m", "safe_high_position_m", "simulation_config", "input_sha256",
}
CONFIG_KEYS = {"sample_period_ms", "hold_duration_ms", "stop_deceleration_m_s2"}
COMMAND_KEYS = {
    "schema_version", "command_id", "sequence", "created_at", "source", "idempotency_key",
    "coordinate_frame", "position_m", "orientation_policy", "target_kind", "executable",
    "max_speed", "max_acceleration", "max_jerk", "timeout_ms", "approach_offset_m",
    "retract_offset_m", "simulation_only", "formal_use_allowed", "promotion_locked",
    "execution_allowed", "entity_action_authorized", "h1_required", "feedback_required",
    "emergency_stop_required_clear", "collision_check_required", "status", "contract_sha256",
}
LOCKS = {
    "simulation_only": True,
    "formal_use_allowed": False,
    "promotion_locked": True,
    "execution_allowed": False,
    "entity_action_authorized": False,
    "h1_required": True,
    "feedback_required": True,
    "emergency_stop_required_clear": True,
    "collision_check_required": True,
}
FALSE_OUTPUTS = {
    "formal_use_allowed": False,
    "execution_allowed": False,
    "entity_action_authorized": False,
    "nano_deployment_authorized": False,
    "motor_command_generated": False,
    "motor_target_generated": False,
    "serial_payload_generated": False,
}


class SimulationError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(value: dict[str, Any], field: str) -> str:
    unsigned = dict(value)
    unsigned.pop(field, None)
    return hashlib.sha256(canonical(unsigned)).hexdigest()


@lru_cache(maxsize=1)
def load_b4_module():
    path = Path(__file__).resolve().parent / "b4_prep" / "m1_m2_motion_sim.py"
    spec = importlib.util.spec_from_file_location("b4_m1_m2_motion_sim", path)
    if spec is None or spec.loader is None:
        raise SimulationError("b4_motion_model_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finite(value: Any, label: str) -> float:
    try:
        return load_b4_module().finite(value, label)
    except ValueError as exc:
        raise SimulationError(str(exc)) from exc


def vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise SimulationError(f"{label}_must_have_three_values")
    return [finite(item, f"{label}_{index}") for index, item in enumerate(value)]


def norm(value: list[float]) -> float:
    return math.sqrt(sum(item * item for item in value))


def distance(left: list[float], right: list[float]) -> float:
    return norm([a - b for a, b in zip(left, right)])


def add(left: list[float], right: list[float]) -> list[float]:
    return [a + b for a, b in zip(left, right)]


def within(point: list[float], limits: tuple[list[float], list[float]]) -> bool:
    return all(lower <= value <= upper for value, lower, upper in zip(point, limits[0], limits[1]))


def box_clearance(point: list[float]) -> float:
    lower = [value - CHASSIS_MARGIN_M for value in CHASSIS_BOX[0]]
    upper = [value + CHASSIS_MARGIN_M for value in CHASSIS_BOX[1]]
    if within(point, (lower, upper)):
        return -min(min(value - lo, hi - value) for value, lo, hi in zip(point, lower, upper))
    gaps = [max(lo - value, 0.0, value - hi) for value, lo, hi in zip(point, lower, upper)]
    return norm(gaps)


def validate_utc(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SimulationError("created_at_must_be_utc_iso8601")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SimulationError("created_at_invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise SimulationError("created_at_must_be_utc")


def validate_offset(value: Any, label: str, target: list[float]) -> list[float]:
    offset = vector(value, label)
    magnitude = norm(offset)
    if magnitude < MIN_OFFSET_M:
        raise SimulationError(f"{label}_must_be_non_contact")
    if magnitude > MAX_OFFSET_M:
        raise SimulationError(f"{label}_exceeds_0.2_m")
    if not within(add(target, offset), WORKSPACE):
        raise SimulationError(f"{label}_endpoint_outside_workspace")
    return offset


def validate_measure(value: Any, label: str, unit: str, maximum: float) -> float:
    if not isinstance(value, dict) or set(value) != {"value", "unit"} or value.get("unit") != unit:
        raise SimulationError(f"{label}_unit_invalid")
    amount = finite(value.get("value"), label)
    if amount <= 0:
        raise SimulationError(f"{label}_must_be_positive")
    if amount > maximum:
        raise SimulationError(f"{label}_exceeds_contract_limit")
    return amount


def validate_command(command: Any) -> dict[str, Any]:
    if not isinstance(command, dict):
        raise SimulationError("command_must_be_object")
    unknown, missing = set(command) - COMMAND_KEYS, COMMAND_KEYS - set(command)
    if unknown:
        raise SimulationError("command_unknown_fields:" + ",".join(sorted(unknown)))
    if missing:
        raise SimulationError("command_missing_fields:" + ",".join(sorted(missing)))
    if command["schema_version"] != CONTRACT_SCHEMA:
        raise SimulationError("command_schema_version_invalid")
    if not isinstance(command["command_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", command["command_id"]):
        raise SimulationError("command_id_invalid")
    if isinstance(command["sequence"], bool) or not isinstance(command["sequence"], int) or command["sequence"] < 0:
        raise SimulationError("command_sequence_invalid")
    validate_utc(command["created_at"])
    if command["source"] not in {"offline_vision", "offline_demo", "simulation_review"}:
        raise SimulationError("command_source_invalid")
    if not isinstance(command["idempotency_key"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", command["idempotency_key"]):
        raise SimulationError("idempotency_key_invalid")
    if command["coordinate_frame"] not in {"robot_base", "robot_base_candidate"}:
        raise SimulationError("coordinate_frame_invalid")
    target = vector(command["position_m"], "position_m")
    if not within(target, WORKSPACE):
        raise SimulationError("target_out_of_workspace")
    if command["orientation_policy"] not in {"keep_current", "tool_z_toward_target", "fixed_identity"}:
        raise SimulationError("orientation_policy_invalid")
    if command["target_kind"] not in {"offline_simulation_only", "non_contact_preview"}:
        raise SimulationError("target_kind_invalid")
    if command["executable"] is not False:
        raise SimulationError("command_executable_must_be_false")
    speed = validate_measure(command["max_speed"], "maximum_speed", "m/s", MAX_SPEED_M_S)
    acceleration = validate_measure(command["max_acceleration"], "maximum_acceleration", "m/s^2", MAX_ACCELERATION_M_S2)
    if command["max_jerk"] != {"supported": False, "value": None, "unit": "unsupported"}:
        raise SimulationError("maximum_jerk_must_be_unsupported")
    timeout = command["timeout_ms"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300_000:
        raise SimulationError("timeout_ms_invalid")
    approach = validate_offset(command["approach_offset_m"], "approach_offset_m", target)
    retract = validate_offset(command["retract_offset_m"], "retract_offset_m", target)
    for field, expected in LOCKS.items():
        if command[field] is not expected:
            raise SimulationError(f"command_{field}_must_be_{str(expected).lower()}")
    if command["status"] not in {"APPROACH", "HOLD", "RETRACT", "RETURN_HIGH", "STOPPED", "BLOCKED", "COMPLETE"}:
        raise SimulationError("command_status_invalid")
    declared = command["contract_sha256"]
    if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{64}", declared):
        raise SimulationError("contract_sha256_format_invalid")
    if declared != content_hash(command, "contract_sha256"):
        raise SimulationError("contract_sha256_mismatch")
    return {"document": command, "target": target, "approach": approach, "retract": retract, "speed": speed, "acceleration": acceleration}


def validate_input(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise SimulationError("input_must_be_object")
    unknown, missing = set(document) - ENVELOPE_KEYS, ENVELOPE_KEYS - set(document)
    if unknown:
        raise SimulationError("input_unknown_fields:" + ",".join(sorted(unknown)))
    if missing:
        raise SimulationError("input_missing_fields:" + ",".join(sorted(missing)))
    if document["schema_version"] != INPUT_SCHEMA or document["synthetic"] is not True:
        raise SimulationError("input_schema_or_synthetic_invalid")
    if document["side"] not in {"left", "right"}:
        raise SimulationError("side_invalid")
    if document["scenario"] not in {"nominal", *FAULTS}:
        raise SimulationError("scenario_invalid")
    command = validate_command(document["command"])
    start = vector(document["start_position_m"], "start_position_m")
    safe = vector(document["safe_high_position_m"], "safe_high_position_m")
    if not within(start, WORKSPACE) or not within(safe, WORKSPACE):
        raise SimulationError("start_or_safe_high_out_of_workspace")
    if safe[2] < MIN_SAFE_HIGH_Z_M:
        raise SimulationError("safe_high_below_minimum")
    config = document["simulation_config"]
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS:
        raise SimulationError("simulation_config_invalid")
    sample_ms, hold_ms = config["sample_period_ms"], config["hold_duration_ms"]
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (sample_ms, hold_ms)):
        raise SimulationError("simulation_timing_invalid")
    stop_deceleration = finite(config["stop_deceleration_m_s2"], "stop_deceleration_m_s2")
    if stop_deceleration <= 0:
        raise SimulationError("stop_deceleration_must_be_positive")
    if command["document"]["timeout_ms"] < sample_ms:
        raise SimulationError("watchdog_shorter_than_sample_period")
    declared = document["input_sha256"]
    if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{64}", declared):
        raise SimulationError("input_sha256_format_invalid")
    if declared != content_hash(document, "input_sha256"):
        raise SimulationError("input_sha256_mismatch")
    return {"document": document, "command": command, "start": start, "safe": safe, "sample_ms": sample_ms, "hold_ms": hold_ms, "stop_deceleration": stop_deceleration}


def path_minimum_clearance(start: list[float], end: list[float], sample_distance: float) -> float:
    length = distance(start, end)
    count = max(1, int(math.ceil(length / max(sample_distance, 0.001))))
    clearances = []
    for index in range(count + 1):
        ratio = index / count
        point = [left + (right - left) * ratio for left, right in zip(start, end)]
        clearances.append(box_clearance(point))
    return min(clearances)


def b4_segment_metrics(start: list[float], end: list[float], speed: float, stop_deceleration: float) -> tuple[int, float, list[float]]:
    length = distance(start, end)
    if length == 0:
        return 0, 0.0, [0.0, 0.0, 0.0]
    b4 = load_b4_module()
    result = b4.simulate({
        "document": {"scenario": "nominal"},
        "config": {"stop_decel_norm_s2": stop_deceleration},
        "segments": [{"side": "left", "actions": [{"kind": "lateral_expand", "distance_norm": length, "speed_norm_s": speed}]}],
    })
    duration_ms = result["total_duration_ms"]
    stopping_distance = result["max_stop_distance_norm"]
    velocity = [0.0, 0.0, 0.0] if length == 0 else [(right - left) / length * speed for left, right in zip(start, end)]
    return duration_ms, stopping_distance, velocity


def b4_fault_events(scenario: str, speed: float, stop_deceleration: float) -> list[dict[str, Any]]:
    if scenario not in {"emergency_stop", "watchdog_timeout", "feedback_loss"}:
        return []
    b4 = load_b4_module()
    action = {"kind": "lateral_expand", "distance_norm": 0.05, "speed_norm_s": speed}
    result = b4.simulate({
        "document": {"scenario": scenario},
        "config": {"stop_decel_norm_s2": stop_deceleration},
        "segments": [{"side": "left", "actions": [dict(action), dict(action), dict(action)]}],
    })
    if result["fault_mode"] != scenario or not result["fault_handled"]:
        raise SimulationError("b4_fault_model_did_not_stop")
    return result["events"]


def base_report(command_id: str | None, side: str | None) -> dict[str, Any]:
    return {
        "schema_version": OUTPUT_SCHEMA,
        "tool_version": TOOL_VERSION,
        "simulation_id": None,
        "command_id": command_id,
        "side": side,
        "simulation_only": True,
        "simulation_valid": False,
        "promotion_locked": True,
        "executable": False,
        **FALSE_OUTPUTS,
        "states": [],
        "metrics": {"minimum_clearance_m": None, "maximum_stopping_distance_m": None, "trajectory_point_count": 0},
        "blocking_reasons": [],
        "final_state": "BLOCKED",
    }


def append_state(report: dict[str, Any], state: str, step: int, timestamp_ms: int, position: list[float], velocity: list[float], target: list[float], clearance: float, stopping_distance: float) -> None:
    report["states"].append({
        "state": state,
        "step": step,
        "timestamp_ms": timestamp_ms,
        "simulated_position_m": position,
        "simulated_velocity_m_s": velocity,
        "distance_to_target_m": distance(position, target),
        "minimum_clearance_m": clearance,
        "stopping_distance_m": stopping_distance,
    })


def finalize_id(report: dict[str, Any]) -> dict[str, Any]:
    identity = dict(report)
    identity["simulation_id"] = None
    report["simulation_id"] = "b6-ee-sim-" + hashlib.sha256(canonical(identity)).hexdigest()[:24]
    return report


def simulate(model: dict[str, Any]) -> dict[str, Any]:
    command, document = model["command"], model["document"]
    report = base_report(command["document"]["command_id"], document["side"])
    report["simulation_valid"] = True
    target = command["target"]
    approach_point = add(target, command["approach"])
    retract_point = add(target, command["retract"])
    speed = command["speed"]
    stop_distance = speed * speed / (2.0 * model["stop_deceleration"])
    available_stop_distance = norm(command["approach"])
    constraint_reasons = []
    if stop_distance > available_stop_distance:
        constraint_reasons.append("stopping_distance_insufficient")
    route = [model["start"], model["safe"], approach_point, retract_point, model["safe"]]
    if any(not within(point, SOFT_LIMITS) for point in route):
        constraint_reasons.append("soft_limit_violation")
    segment_clearances = [path_minimum_clearance(left, right, speed * model["sample_ms"] / 1000.0) for left, right in zip(route, route[1:])]
    minimum_clearance = min([box_clearance(model["start"]), *segment_clearances])
    if minimum_clearance < 0:
        constraint_reasons.append("collision_detected")
    timestamp, step = 0, 0
    append_state(report, "IDLE", step, timestamp, model["start"], [0.0, 0.0, 0.0], target, box_clearance(model["start"]), 0.0)
    duration, moving_stop, velocity = b4_segment_metrics(model["start"], model["safe"], speed, model["stop_deceleration"])
    timestamp += duration
    step += 1
    append_state(report, "SAFE_HIGH", step, timestamp, model["safe"], velocity, target, segment_clearances[0], moving_stop)

    scenario = document["scenario"]
    b4_events = b4_fault_events(scenario, speed, model["stop_deceleration"])
    reasons = list(dict.fromkeys(constraint_reasons))
    if scenario != "nominal" and scenario not in reasons:
        reasons.append(scenario)
    if reasons:
        structural = {"stopping_distance_insufficient", "target_out_of_workspace"}
        report["blocking_reasons"] = reasons
        if any(reason in structural for reason in reasons):
            report["simulation_valid"] = False
            terminal = "BLOCKED"
        else:
            terminal = "STOPPED"
        step += 1
        timestamp += model["sample_ms"]
        append_state(report, terminal, step, timestamp, model["safe"], [0.0, 0.0, 0.0], target, minimum_clearance, stop_distance)
        report["final_state"] = terminal
    else:
        phases = (
            ("APPROACH", approach_point, 0, segment_clearances[1]),
            ("HOLD", approach_point, model["hold_ms"], box_clearance(approach_point)),
            ("RETRACT", retract_point, 0, segment_clearances[2]),
            ("RETURN_HIGH", model["safe"], 0, segment_clearances[3]),
        )
        current = model["safe"]
        for state, position, pause_ms, clearance in phases:
            step += 1
            if state == "HOLD":
                timestamp += pause_ms
                velocity = [0.0, 0.0, 0.0]
                moving_stop = 0.0
            else:
                duration, moving_stop, velocity = b4_segment_metrics(current, position, speed, model["stop_deceleration"])
                timestamp += duration
            append_state(report, state, step, timestamp, position, velocity, target, clearance, moving_stop)
            current = position
        step += 1
        append_state(report, "COMPLETE", step, timestamp, model["safe"], [0.0, 0.0, 0.0], target, box_clearance(model["safe"]), 0.0)
        report["final_state"] = "COMPLETE"
    report["metrics"] = {
        "minimum_clearance_m": minimum_clearance,
        "maximum_stopping_distance_m": stop_distance,
        "available_non_contact_stop_distance_m": available_stop_distance,
        "maximum_speed_m_s": speed,
        "maximum_acceleration_m_s2": command["acceleration"],
        "trajectory_point_count": len(report["states"]),
    }
    report["safety_model"] = {
        "source": "scripts/b4_prep/m1_m2_motion_sim.py",
        "tool_version": load_b4_module().TOOL_VERSION,
        "fault_events": b4_events,
    }
    return finalize_id(report)


def blocked(document: Any, error: Exception) -> dict[str, Any]:
    command = document.get("command", {}) if isinstance(document, dict) else {}
    report = base_report(command.get("command_id") if isinstance(command, dict) else None, document.get("side") if isinstance(document, dict) else None)
    report["blocking_reasons"] = [str(error)]
    return finalize_id(report)


def run_document(document: Any) -> dict[str, Any]:
    try:
        return simulate(validate_input(document))
    except (SimulationError, TypeError, ValueError, OverflowError) as error:
        return blocked(document, error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.out.resolve():
            raise SimulationError("output_must_not_overwrite_input")
        document = json.loads(args.input.read_text(encoding="utf-8"))
        result = run_document(document)
    except (OSError, UnicodeError, json.JSONDecodeError, SimulationError) as error:
        result = blocked({}, error)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"simulation_valid": result["simulation_valid"], "simulation_id": result["simulation_id"], "final_state": result["final_state"], "blocking_reasons": result["blocking_reasons"]}, ensure_ascii=False, sort_keys=True))
    return 0 if result["simulation_valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
