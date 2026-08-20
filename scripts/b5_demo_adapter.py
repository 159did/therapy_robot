#!/usr/bin/env python3
"""Adapt the real B5-M1/M2 and B5-VISION offline output contracts.

This adapter reads result JSON only. It never invokes either producer, opens a
device, sends an HTTP request, writes shared memory, or creates a motor target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "b5.demo-adapter.v1"
ROUTE_SCHEMA = "b5.m1-m2-sim.v1"
VISION_SCHEMA = "b5.vision-offline.v1"
MIN_COORDINATE_CONFIDENCE = 0.55
REQUIRED_PERMISSION_FIELDS = (
    "execution_allowed",
    "entity_action_authorized",
    "nano_deployment_authorized",
)
REQUIRED_HARDWARE_FIELDS = (
    "d405_accessed",
    "camera_device_opened",
    "nano_accessed",
    "serial_accessed",
    "motor_command_generated",
)
FIXED_FALSE = {
    "execution_allowed": False,
    "entity_action_authorized": False,
    "nano_deployment_authorized": False,
    "entity_serial_accessed": False,
    "entity_d405_accessed": False,
    "motor_enabled": False,
    "motor_zeroed": False,
    "motor_moved": False,
    "motor_command_generated": False,
}


class AdapterError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"{label}_json_invalid:{exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError(f"{label}_must_be_object")
    return value


def require_false(value: dict[str, Any], label: str) -> None:
    for key in REQUIRED_PERMISSION_FIELDS:
        if key not in value:
            raise AdapterError(f"{label}_{key}_missing")
    for key in FIXED_FALSE:
        if key in value and value[key] is not False:
            raise AdapterError(f"{label}_{key}_must_be_false")


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise AdapterError(f"{label}_not_finite")
    return float(value)


def validate_route(route: dict[str, Any], side: str) -> dict[str, Any]:
    if route.get("schema_version") != ROUTE_SCHEMA:
        raise AdapterError("route_schema_invalid")
    if route.get("simulation_valid") is not True or route.get("status") != "PASS":
        raise AdapterError("route_simulation_failed")
    if route.get("synthetic") is not True or route.get("route_side") != side:
        raise AdapterError("route_side_or_synthetic_invalid")
    expected = ["SAFE_HIGH", "LEFT_CAMERA_POSITION" if side == "left" else "RIGHT_CAMERA_POSITION", "SAFE_HIGH"]
    if route.get("route_states") != expected or route.get("final_pose") != "STOWED":
        raise AdapterError("route_states_or_final_pose_invalid")
    if route.get("blocking_reasons") not in (None, []):
        raise AdapterError("route_blocking_reasons_present")
    require_false(route, "route")
    if route.get("formal_use_allowed") is not False or route.get("promotion_locked") is not True:
        raise AdapterError("route_promotion_lock_invalid")
    metrics = route.get("metrics")
    if not isinstance(metrics, dict) or isinstance(metrics.get("action_count"), bool) or not isinstance(metrics.get("action_count"), int) or metrics.get("action_count", 0) <= 0:
        raise AdapterError("route_metrics_invalid")
    return {"simulation_id": route.get("simulation_id"), "route_states": expected, "final_pose": route["final_pose"], "metrics": metrics, "source_payload_sha256": route.get("source", {}).get("payload_sha256")}


def validate_vision(vision: dict[str, Any]) -> dict[str, Any]:
    if vision.get("schema_version") != VISION_SCHEMA:
        raise AdapterError("vision_schema_invalid")
    if vision.get("pipeline_valid") is not True or vision.get("offline_simulation_valid") is not True:
        raise AdapterError("vision_pipeline_failed")
    if vision.get("synthetic") not in (None, True):
        raise AdapterError("vision_must_be_synthetic")
    require_false(vision, "vision")
    if vision.get("formal_use_allowed") is not False or vision.get("promotion_locked") is not True:
        raise AdapterError("vision_promotion_lock_invalid")
    hardware = vision.get("hardware_access")
    if not isinstance(hardware, dict) or any(key not in hardware or hardware[key] is not False for key in REQUIRED_HARDWARE_FIELDS) or any(value is not False for value in hardware.values()):
        raise AdapterError("vision_hardware_access_not_false")
    points = vision.get("acupoints")
    if not isinstance(points, list) or not points:
        raise AdapterError("vision_acupoints_missing")
    valid_points = []
    for index, point in enumerate(points):
        if not isinstance(point, dict) or point.get("valid") is not True:
            continue
        confidence = finite(point.get("coordinate_confidence"), f"vision_acupoint_{index}_confidence")
        if confidence < MIN_COORDINATE_CONFIDENCE:
            raise AdapterError(f"vision_acupoint_{index}_confidence_below_threshold")
        target = point.get("simulation_endpoint_target")
        if not isinstance(target, dict) or target.get("executable") is not False:
            raise AdapterError(f"vision_acupoint_{index}_target_invalid")
        position = target.get("position_m")
        if not isinstance(position, list) or len(position) != 3:
            raise AdapterError(f"vision_acupoint_{index}_position_invalid")
        try:
            position = [finite(value, f"vision_acupoint_{index}_position") for value in position]
        except AdapterError as exc:
            raise AdapterError(f"vision_acupoint_{index}_position_invalid") from exc
        valid_points.append({"name": point.get("name"), "pixel": point.get("pixel"), "coordinate_confidence": confidence, "point_robot_candidate_m": point.get("point_robot_candidate_m"), "simulation_endpoint_target": target})
    if not valid_points:
        raise AdapterError("vision_no_valid_acupoint_target")
    return {"pipeline_id": vision.get("pipeline_id"), "acupoints": valid_points, "selected": valid_points[0], "formal_blocking_reasons": vision.get("formal_blocking_reasons", [])}


def base_report(side: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "valid": False,
        "current_stage": "IDLE",
        "states": ["IDLE"],
        "side": side,
        "route": {"passed": False, "simulation_id": None, "route_states": []},
        "vision": {"passed": False, "pipeline_id": None, "acupoints": [], "selected_acupoint": None},
        "candidate_end_effector_position_m": None,
        "simulation_only": True,
        "final_state": "BLOCKED",
        "blocking_reasons": [],
        **FIXED_FALSE,
    }


def run(route_path: Path, vision_path: Path, side: str, expected_route_hash: str | None = None, expected_vision_hash: str | None = None) -> dict[str, Any]:
    report = base_report(side)
    try:
        if side not in ("left", "right"):
            raise AdapterError("side_invalid")
        route_hash = file_hash(route_path)
        vision_hash = file_hash(vision_path)
        if expected_route_hash and route_hash != expected_route_hash:
            raise AdapterError("route_input_hash_changed")
        if expected_vision_hash and vision_hash != expected_vision_hash:
            raise AdapterError("vision_input_hash_changed")
        report["states"].append("SAFE_HIGH")
        route = validate_route(load(route_path, "route"), side)
        report["route"] = {"passed": True, **route, "input_sha256": route_hash}
        report["states"].append("CAMERA_READY")
        vision = validate_vision(load(vision_path, "vision"))
        report["vision"] = {"passed": True, "pipeline_id": vision["pipeline_id"], "acupoints": vision["acupoints"], "selected_acupoint": vision["selected"], "input_sha256": vision_hash}
        report["states"].append("ACUPOINT_FOUND")
        report["candidate_end_effector_position_m"] = vision["selected"]["simulation_endpoint_target"]["position_m"]
        report["states"].extend(["APPROACH_SIMULATED", "HOLD", "RETRACT", "RETURN_HIGH", "COMPLETE"])
        report["current_stage"] = report["final_state"] = "COMPLETE"
        report["valid"] = True
    except (AdapterError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        report["current_stage"] = report["final_state"] = "BLOCKED"
        report["states"].append("BLOCKED")
        report["blocking_reasons"] = [str(exc)]
    identity = {key: value for key, value in report.items() if key not in {"demo_id"}}
    report["demo_id"] = "b5-demo-adapter-" + hashlib.sha256(canonical(identity)).hexdigest()[:16]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--vision", type=Path, required=True)
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--expected-route-sha256")
    parser.add_argument("--expected-vision-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args.route, args.vision, args.side, args.expected_route_sha256, args.expected_vision_sha256)
    except Exception as exc:  # output must remain inspectable even for missing paths
        report = base_report(args.side)
        report["states"].append("BLOCKED")
        report["blocking_reasons"] = [str(exc)]
        report["demo_id"] = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "current_stage": report["current_stage"], "side": report["side"], "demo_id": report["demo_id"], "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
