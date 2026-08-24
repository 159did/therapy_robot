#!/usr/bin/env python3
"""Run the complete therapy-robot experiment workflow as a locked report.

The default mode consumes already-validated offline route and vision JSON.
It produces a deterministic observation report and never opens hardware. A
future entity run must still pass the H1 and central control gate; this entry
point intentionally reports a blocking reason instead of bypassing that gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
from pathlib import Path
from typing import Any


SCHEMA = "ptr.experiment-workflow.v1"
LOCKED = {
    "execution_allowed": False,
    "entity_action_authorized": False,
    "nano_deployment_authorized": False,
    "entity_serial_accessed": False,
    "entity_d405_accessed": False,
    "motor_command_generated": False,
    "motor_enabled": False,
    "motor_moved": False,
}
STAGES = ("BOOT", "SAFE_HIGH", "SIDE_ROTATED", "ARM_EXTENDED", "CAMERA_CAPTURED", "ACUPOINTS_READ", "HOVER_TARGET", "HOLD_NO_CONTACT", "RETRACTED", "RETURN_HIGH", "COMPLETE")


def load_adapter():
    path = Path(__file__).resolve().with_name("b5_demo_adapter.py")
    spec = importlib.util.spec_from_file_location("therapy_robot_b5_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("b5_demo_adapter_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def base_report(side: str, mode: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "valid": False, "mode": mode, "host": {"hostname": platform.node(), "architecture": platform.machine()}, "side": side, "current_stage": "BOOT", "states": ["BOOT"], "stage_details": [], "blocking_reasons": [], "simulation_only": mode == "offline", **LOCKED}


def run(route: Path, vision: Path, side: str, mode: str = "offline") -> dict[str, Any]:
    report = base_report(side, mode)
    try:
        if side not in {"left", "right"}:
            raise ValueError("side_invalid")
        if mode not in {"offline", "hardware"}:
            raise ValueError("mode_invalid")
        if mode == "hardware":
            raise ValueError("hardware_execution_requires_h1_and_central_gate")
        adapter = load_adapter()
        route_hash, vision_hash = sha256(route), sha256(vision)
        adapted = adapter.run(route, vision, side, route_hash, vision_hash)
        if not adapted["valid"]:
            raise ValueError(adapted["blocking_reasons"][0] if adapted["blocking_reasons"] else "offline_inputs_invalid")
        selected = adapted["vision"]["selected_acupoint"]
        target = selected["simulation_endpoint_target"]
        details = {
            "BOOT": {"run_mode": "offline", "end_effector_installed": False},
            "SAFE_HIGH": {"route_state": adapted["route"]["route_states"][0], "height_reference": "safe_high"},
            "SIDE_ROTATED": {"route_state": adapted["route"]["route_states"][1], "side": side, "motion": "simulated"},
            "ARM_EXTENDED": {"route_state": "high_plane_deployment", "motion": "simulated"},
            "CAMERA_CAPTURED": {"source": "validated_offline_bundle", "camera_device_opened": False},
            "ACUPOINTS_READ": {"count": len(adapted["vision"]["acupoints"]), "pipeline_id": adapted["vision"]["pipeline_id"]},
            "HOVER_TARGET": {"position_m": target["position_m"], "executable": False, "contact": False},
            "HOLD_NO_CONTACT": {"duration_s": 0, "contact": False},
            "RETRACTED": {"route_state": "retract_offset", "contact": False},
            "RETURN_HIGH": {"route_state": adapted["route"]["route_states"][-1]},
            "COMPLETE": {"entity_result": "not_run"},
        }
        report.update({"valid": True, "current_stage": "COMPLETE", "states": list(STAGES), "stage_details": [{"stage": name, "detail": details[name]} for name in STAGES], "route_input_sha256": route_hash, "vision_input_sha256": vision_hash, "selected_acupoint": selected, "candidate_hover_position_m": target["position_m"]})
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        report["current_stage"] = "BLOCKED"
        report["states"].append("BLOCKED")
        report["blocking_reasons"] = [str(exc)]
    identity = {key: value for key, value in report.items() if key != "report_id"}
    report["report_id"] = "workflow-" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()[:16]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--vision", type=Path, required=True)
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--mode", choices=("offline", "hardware"), default="offline")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.route, args.vision, args.side, args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "current_stage": report["current_stage"], "report_id": report["report_id"], "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
