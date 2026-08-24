#!/usr/bin/env python3
"""Run the complete no-contact observation workflow from checked fixtures.

This is an offline orchestration report. It models the intended order of the
physical workflow while keeping all execution and hardware permissions false.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


SCHEMA = "ptr.observation-flow.v1"
STAGES = (
    "BOOT",
    "SAFE_HIGH",
    "SIDE_ROTATED",
    "ARM_EXTENDED",
    "CAMERA_CAPTURED",
    "ACUPOINTS_READ",
    "HOVER_TARGET",
    "HOLD_NO_CONTACT",
    "RETRACTED",
    "RETURN_HIGH",
    "COMPLETE",
)
LOCKED = {
    "execution_allowed": False,
    "entity_action_authorized": False,
    "nano_deployment_authorized": False,
    "entity_serial_accessed": False,
    "entity_d405_accessed": False,
    "motor_command_generated": False,
    "motor_enabled": False,
    "motor_zeroed": False,
    "motor_moved": False,
}


def load_adapter():
    path = Path(__file__).resolve().parent / "b5_demo_adapter.py"
    spec = importlib.util.spec_from_file_location("b5_demo_adapter_for_observation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("b5_demo_adapter_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(route: Path, vision: Path, side: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": SCHEMA,
        "valid": False,
        "current_stage": "BOOT",
        "states": ["BOOT"],
        "side": side,
        "simulation_only": True,
        "physical_action": "not_performed",
        "route_input_sha256": None,
        "vision_input_sha256": None,
        "selected_acupoint": None,
        "candidate_hover_position_m": None,
        "stage_details": [],
        "blocking_reasons": [],
        **LOCKED,
    }
    try:
        if side not in {"left", "right"}:
            raise ValueError("side_invalid")
        adapter = load_adapter()
        route_hash = sha256(route)
        vision_hash = sha256(vision)
        adapted = adapter.run(route, vision, side, route_hash, vision_hash)
        if not adapted["valid"]:
            raise ValueError(adapted["blocking_reasons"][0])
        selected = adapted["vision"]["selected_acupoint"]
        hover = selected["simulation_endpoint_target"]["position_m"]
        report["route_input_sha256"] = route_hash
        report["vision_input_sha256"] = vision_hash
        report["selected_acupoint"] = selected
        report["candidate_hover_position_m"] = hover
        detail = {
            "BOOT": {"run_mode": "offline_simulation", "end_effector_installed": False},
            "SAFE_HIGH": {"route_state": adapted["route"]["route_states"][0], "height_reference": "safe_high"},
            "SIDE_ROTATED": {"route_state": adapted["route"]["route_states"][1], "side": side},
            "ARM_EXTENDED": {"action": "high_plane_deployment", "source_action_count": adapted["route"]["metrics"]["action_count"]},
            "CAMERA_CAPTURED": {"source": "checked_offline_vision_fixture", "camera_opened": False},
            "ACUPOINTS_READ": {"count": len(adapted["vision"]["acupoints"]), "pipeline_id": adapted["vision"]["pipeline_id"]},
            "HOVER_TARGET": {"position_m": hover, "executable": False, "contact": False},
            "HOLD_NO_CONTACT": {"duration_s": 0, "contact": False},
            "RETRACTED": {"route_state": "retract_offset", "contact": False},
            "RETURN_HIGH": {"route_state": adapted["route"]["route_states"][-1]},
            "COMPLETE": {"entity_result": "not_run"},
        }
        report["stage_details"] = [{"stage": name, "detail": detail[name]} for name in STAGES]
        report["states"] = list(STAGES)
        report["current_stage"] = "COMPLETE"
        report["valid"] = True
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        report["states"].append("BLOCKED")
        report["current_stage"] = "BLOCKED"
        report["blocking_reasons"] = [str(exc)]
    identity = dict(report)
    identity.pop("report_id", None)
    report["report_id"] = "observation-" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--vision", type=Path, required=True)
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.route, args.vision, args.side)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "current_stage": report["current_stage"], "report_id": report["report_id"], "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
