#!/usr/bin/env python3
"""Run the graduation-demo photo -> vision -> approach flow offline.

The flow consumes only synthetic files. It never imports or calls hardware,
serial, shared-memory, HTTP-control, or deployment code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "b5.demo-flow.v1"
VISION_SCHEMA = "b5.demo-vision.v1"
ROUTE_SCHEMA = "b5.demo-route.v1"
STAGES = ("IDLE", "SAFE_HIGH", "CAMERA_READY", "ACUPOINT_FOUND", "APPROACH_SIMULATED", "HOLD", "RETRACT", "RETURN_HIGH", "COMPLETE")
FIXED_FALSE = {
    "execution_allowed": False,
    "entity_action_authorized": False,
    "nano_deployment_authorized": False,
    "entity_serial_accessed": False,
    "entity_d405_accessed": False,
    "motor_enabled": False,
    "motor_zeroed": False,
    "motor_moved": False,
}


class DemoError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise DemoError(f"{label}_must_be_finite")
    return float(value)


def require_locked(document: dict[str, Any], label: str) -> None:
    for key in FIXED_FALSE:
        if document.get(key) is not False:
            raise DemoError(f"{label}_{key}_must_be_false")


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoError(f"{label}_json_invalid:{exc}") from exc
    if not isinstance(value, dict):
        raise DemoError(f"{label}_must_be_object")
    return value


def validate_vision(document: dict[str, Any], image_sha256: str | None = None) -> list[dict[str, float]]:
    if document.get("schema_version") != VISION_SCHEMA or document.get("synthetic") is not True:
        raise DemoError("vision_schema_or_synthetic_invalid")
    require_locked(document, "vision")
    if "image_sha256" in document and document["image_sha256"] != image_sha256:
        raise DemoError("image_input_hash_changed")
    if document.get("quality_valid") is not True:
        raise DemoError("vision_quality_invalid")
    confidence = finite(document.get("confidence"), "vision_confidence")
    if confidence < 0.85:
        raise DemoError("vision_confidence_below_threshold")
    points = document.get("acupoints")
    if not isinstance(points, list) or not points:
        raise DemoError("acupoints_missing")
    result: list[dict[str, float]] = []
    for index, point in enumerate(points):
        if not isinstance(point, dict) or set(point) != {"name", "x_norm", "y_norm", "z_norm"}:
            raise DemoError(f"acupoint_{index}_schema_invalid")
        if not isinstance(point["name"], str) or not point["name"]:
            raise DemoError(f"acupoint_{index}_name_invalid")
        coords = {axis: finite(point[f"{axis}_norm"], f"acupoint_{index}_{axis}") for axis in ("x", "y", "z")}
        if any(abs(value) > 1.0 for value in coords.values()):
            raise DemoError(f"acupoint_{index}_outside_normalized_bounds")
        result.append({"name": point["name"], **coords})
    return result


def validate_route(document: dict[str, Any], side: str, point: dict[str, float], vision_sha256: str | None = None) -> dict[str, Any]:
    if document.get("schema_version") != ROUTE_SCHEMA or document.get("synthetic") is not True:
        raise DemoError("route_schema_or_synthetic_invalid")
    require_locked(document, "route")
    if "vision_sha256" in document and document["vision_sha256"] != vision_sha256:
        raise DemoError("vision_input_hash_changed")
    if document.get("side") != side or document.get("valid") is not True:
        raise DemoError("route_simulation_invalid")
    if document.get("fail_route") is True:
        raise DemoError("route_simulation_failed")
    waypoints = document.get("waypoints")
    if not isinstance(waypoints, dict) or set(waypoints) != {"safe_high", "approach_offset", "retract_offset", "return_high"}:
        raise DemoError("route_waypoints_invalid")
    target = {}
    for key in ("x_norm", "y_norm", "z_norm"):
        target[key] = finite(point[key[0]], f"target_{key}")
    offset = finite(document.get("non_contact_offset_norm"), "non_contact_offset_norm")
    if offset <= 0:
        raise DemoError("non_contact_offset_invalid")
    approach_target = {"x_norm": target["x_norm"], "y_norm": target["y_norm"], "z_norm": target["z_norm"] + offset}
    for name, waypoint in waypoints.items():
        if not isinstance(waypoint, dict):
            raise DemoError(f"route_{name}_invalid")
        for key in ("x_norm", "y_norm", "z_norm"):
            finite(waypoint.get(key), f"route_{name}_{key}")
    return {"side": side, "target": target, "approach_target": approach_target, "offset_norm": offset, "waypoints": waypoints}


def base_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "valid": False,
        "current_stage": "IDLE",
        "states": ["IDLE"],
        "image": {"passed": False, "sha256": None, "bytes": 0},
        "vision": {"passed": False, "confidence": None, "acupoints": []},
        "simulation": {"passed": False, "side": None, "end_effector_target": None, "approach_target": None, "return_high_target": None, "non_contact_offset_norm": None},
        "execution_allowed": False,
        "blocking_reasons": [],
        **FIXED_FALSE,
    }


def run(image_path: Path, vision_path: Path, route_path: Path, side: str, stop_after: str | None = None) -> dict[str, Any]:
    report = base_report()
    report["side"] = side
    try:
        if side not in ("left", "right"):
            raise DemoError("side_invalid")
        report["states"].append("SAFE_HIGH")
        if not image_path.exists() or not image_path.is_file():
            raise DemoError("image_missing")
        image_bytes = image_path.read_bytes()
        if not image_bytes:
            raise DemoError("image_empty")
        report["image"] = {"passed": True, "sha256": sha256_bytes(image_bytes), "bytes": len(image_bytes)}
        report["states"].append("CAMERA_READY")
        vision = load_json(vision_path, "vision")
        image_sha256 = report["image"]["sha256"]
        points = validate_vision(vision, image_sha256)
        report["vision"] = {"passed": True, "confidence": float(vision["confidence"]), "acupoints": points}
        report["states"].append("ACUPOINT_FOUND")
        route = validate_route(load_json(route_path, "route"), side, points[0], sha256_file(vision_path))
        report["simulation"] = {"passed": True, "side": side, "end_effector_target": route["target"], "approach_target": route["approach_target"], "return_high_target": route["waypoints"]["return_high"], "non_contact_offset_norm": route["offset_norm"]}
        report["states"].append("APPROACH_SIMULATED")
        if stop_after == "APPROACH_SIMULATED":
            report["states"].append("STOPPED")
            report["current_stage"] = "STOPPED"
            report["blocking_reasons"] = ["operator_stop_requested"]
            return finalize(report)
        report["states"].append("HOLD")
        if stop_after == "HOLD":
            report["states"].append("STOPPED")
            report["current_stage"] = "STOPPED"
            report["blocking_reasons"] = ["operator_stop_requested"]
            return finalize(report)
        report["states"].extend(["RETRACT", "RETURN_HIGH", "COMPLETE"])
        report["current_stage"] = "COMPLETE"
        report["valid"] = True
        return finalize(report)
    except (DemoError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        report["current_stage"] = "BLOCKED"
        report["states"].append("BLOCKED")
        report["blocking_reasons"] = [str(exc)]
        return finalize(report)


def finalize(report: dict[str, Any]) -> dict[str, Any]:
    identity = {key: value for key, value in report.items() if key not in {"demo_id", "generated_at_utc"}}
    report["demo_id"] = "b5-demo-" + sha256_bytes(canonical(identity))[:16]
    report["input_hash"] = sha256_bytes(canonical({"image": report["image"], "vision": report["vision"], "simulation": report["simulation"], "side": report.get("side")}))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--vision", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--stop-after", choices=("APPROACH_SIMULATED", "HOLD"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.image, args.vision, args.route, args.side, args.stop_after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "current_stage": report["current_stage"], "demo_id": report["demo_id"], "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
