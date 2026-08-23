#!/usr/bin/env python3
"""Simplified B5 M1/M2 route view backed by the B4-PREP-C simulator.

This adapter exposes only three route states. It never creates motor targets,
opens devices, or changes the B4 normalized motion model.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "b5.m1-m2-sim-input.v1"
OUTPUT_SCHEMA = "b5.m1-m2-sim.v1"
ROUTE_STATES = ("SAFE_HIGH", "LEFT_CAMERA_POSITION", "RIGHT_CAMERA_POSITION")
SCENARIOS = ("nominal", "emergency_stop", "watchdog_timeout", "feedback_loss")
REQUIRED_KEYS = {"schema_version", "synthetic", "source", "route_side", "scenario", "b4_input", "payload_sha256"}
SOURCE_KEYS = {"kind", "fixture_id"}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def payload_sha256(document: dict[str, Any]) -> str:
    unsigned = dict(document)
    unsigned.pop("payload_sha256", None)
    return hashlib.sha256(canonical(unsigned).encode("utf-8")).hexdigest()


def load_b4_module():
    path = Path(__file__).resolve().parents[1] / "b4_prep" / "m1_m2_motion_sim.py"
    spec = importlib.util.spec_from_file_location("b4_m1_m2_motion_sim", path)
    if spec is None or spec.loader is None:
        raise ValueError("b4_simulator_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_safety_module():
    path = Path(__file__).resolve().parents[1] / "b6" / "safety_baseline.py"
    spec = importlib.util.spec_from_file_location("b5_route_safety_baseline", path)
    if spec is None or spec.loader is None:
        raise ValueError("safety_baseline_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"non_finite_{name}")
    return float(value)


def validate_input(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("input_not_object")
    unknown = set(document) - REQUIRED_KEYS
    missing = REQUIRED_KEYS - set(document)
    if unknown:
        raise ValueError("unknown_input_fields:" + ",".join(sorted(unknown)))
    if missing:
        raise ValueError("missing_input_fields:" + ",".join(sorted(missing)))
    if document["schema_version"] != INPUT_SCHEMA or document["synthetic"] is not True:
        raise ValueError("synthetic_schema_or_flag_invalid")
    source = document["source"]
    if not isinstance(source, dict) or set(source) != SOURCE_KEYS or source["kind"] != "synthetic_fixture" or not isinstance(source["fixture_id"], str) or not source["fixture_id"]:
        raise ValueError("synthetic_source_invalid")
    if document["route_side"] not in ("left", "right"):
        raise ValueError("route_side_invalid")
    if document["scenario"] not in SCENARIOS:
        raise ValueError("scenario_invalid")
    if not isinstance(document["b4_input"], dict):
        raise ValueError("b4_input_invalid")
    declared = document["payload_sha256"]
    if not isinstance(declared, str) or len(declared) != 64 or any(c not in "0123456789abcdef" for c in declared):
        raise ValueError("payload_sha256_format_invalid")
    if declared != payload_sha256(document):
        raise ValueError("payload_sha256_mismatch")
    return document


def run(document: dict[str, Any]) -> dict[str, Any]:
    safety = load_safety_module()
    safety_decision = safety.evaluate_control_request(
        safety.SafetyState.default(),
        {"action": safety.ACTION_OFFLINE_SIMULATION, "units": safety.NORMALIZED_UNITS},
    )
    if not safety_decision.allowed or safety_decision.execution_allowed:
        raise ValueError("safety_gate_rejected:" + ",".join(safety_decision.reasons))
    b4 = load_b4_module()
    nested = copy.deepcopy(document["b4_input"])
    nested["scenario"] = document["scenario"]
    # Run the selected side first so a fault injected at the B4 model's
    # deterministic action boundary is observable for either route.
    nested["segments"] = sorted(nested["segments"], key=lambda segment: segment["side"] != document["route_side"])
    nested["payload_sha256"] = b4.payload_sha256(nested)
    model = b4.validate_input(nested)
    simulation = b4.simulate(model)
    side = document["route_side"]
    side_trace = [item for item in simulation["states"] if item["side"] == side]
    if not side_trace:
        raise ValueError("selected_route_trace_missing")
    fault = simulation["fault_mode"]
    side_label = "LEFT_CAMERA_POSITION" if side == "left" else "RIGHT_CAMERA_POSITION"
    if fault is None:
        route_states = ["SAFE_HIGH", side_label, "SAFE_HIGH"]
        status = "PASS"
        final_pose = "STOWED"
        reason = []
    else:
        route_states = ["SAFE_HIGH"]
        status = "FAIL_CLOSED"
        final_pose = "STOPPED"
        reason = [fault + "_safe_stop"]
    return {
        "schema_version": OUTPUT_SCHEMA,
        "simulation_valid": True,
        "status": status,
        "synthetic": True,
        "route_side": side,
        "route_states": route_states,
        "final_pose": final_pose,
        "scenario": document["scenario"],
        "safety_decision": safety_decision.as_dict(),
        "simulation_id": simulation_id(document, side, simulation),
        "metrics": {
            "minimum_speed_norm_s": min(item["speed_norm_s"] for item in side_trace),
            "minimum_displacement_norm": min(item["distance_norm"] for item in side_trace),
            "max_stop_distance_norm": max(item["stopping_distance_norm"] for item in side_trace),
            "watchdog_timeout_ms": model["config"]["watchdog_timeout_ms"],
            "action_count": len(side_trace),
        },
        "events": simulation["events"],
        "checks": {
            "minimum_speed": True,
            "minimum_displacement": True,
            "stop_distance": True,
            "fault_fail_closed": fault is None or simulation["fault_handled"],
            "route_returns_safe_high": fault is None,
            "recovery_requires_new_authorization": True,
        },
        "blocking_reasons": reason,
        "promotion_locked": True,
        "formal_use_allowed": False,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "source": {"fixture_id": document["source"]["fixture_id"], "payload_sha256": document["payload_sha256"]},
    }


def simulation_id(document: dict[str, Any], side: str, simulation: dict[str, Any]) -> str:
    stable = {"input": document, "side": side, "events": simulation["events"], "action_count": simulation["action_count"], "max_stop_distance_norm": simulation["max_stop_distance_norm"]}
    return "b5-sim-" + hashlib.sha256(canonical(stable).encode("utf-8")).hexdigest()[:24]


def blocked(error: Exception) -> dict[str, Any]:
    return {
        "schema_version": OUTPUT_SCHEMA,
        "simulation_valid": False,
        "status": "BLOCKED",
        "synthetic": True,
        "route_states": [],
        "final_pose": "UNKNOWN",
        "simulation_id": None,
        "safety_decision": None,
        "blocking_reasons": [str(error)],
        "promotion_locked": True,
        "formal_use_allowed": False,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.out.resolve():
            raise ValueError("output_must_not_overwrite_input")
        document = json.loads(args.input.read_text(encoding="utf-8"))
        result = run(validate_input(document))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        result = blocked(error)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["simulation_valid"], "status": result["status"], "simulation_id": result["simulation_id"], "blocking_reasons": result["blocking_reasons"]}, ensure_ascii=False, sort_keys=True))
    return 0 if result["simulation_valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
