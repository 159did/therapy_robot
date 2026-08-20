#!/usr/bin/env python3
"""Compose the B6 safety gate, command contract, and offline simulator.

This module is deliberately side-effect free apart from its optional JSON CLI.
It has no device, serial, camera, network, deployment, or motor-control entry
point. The only accepted action is an offline simulation under the locked
SIMULATION safety state.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


SCHEMA = "b6.end-effector-offline-pipeline.v1"
LOCKED_OUTPUTS = {
    "execution_allowed": False,
    "entity_action_authorized": False,
    "nano_deployment_authorized": False,
    "motor_command_generated": False,
    "motor_target_generated": False,
    "serial_payload_generated": False,
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_unavailable:{path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def load_safety_module():
    return _load("b6_pipeline_safety", Path(__file__).with_name("safety_baseline.py"))


@lru_cache(maxsize=1)
def load_contract_module():
    return _load("b6_pipeline_contract", Path(__file__).with_name("validate_end_effector_command.py"))


@lru_cache(maxsize=1)
def load_simulator_module():
    return _load("b6_pipeline_simulator", Path(__file__).resolve().parents[1] / "b6_ee_sim.py")


def _base_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "pipeline_valid": False,
        "final_state": "BLOCKED",
        "completed_stages": [],
        "blocking_reasons": [],
        "safety_decision": None,
        "contract_validation": None,
        "simulation": None,
        **LOCKED_OUTPUTS,
    }


def run_document(document: Any) -> dict[str, Any]:
    """Run the three offline stages in their required fail-closed order."""

    report = _base_report()
    safety = load_safety_module()
    decision = safety.evaluate_control_request(
        safety.SafetyState.default(),
        {"action": safety.ACTION_OFFLINE_SIMULATION, "units": safety.NORMALIZED_UNITS},
    )
    report["safety_decision"] = decision.as_dict()
    if not decision.allowed or decision.execution_allowed:
        report["blocking_reasons"] = ["offline_safety_gate_rejected"]
        return report
    report["completed_stages"].append("SAFETY_BASELINE")

    command = document.get("command") if isinstance(document, dict) else None
    contract = load_contract_module()
    try:
        validation = contract.validate(command)
    except (contract.ContractError, TypeError, ValueError) as exc:
        validation = contract.blocked(exc)
    report["contract_validation"] = validation
    if not validation["valid"]:
        report["blocking_reasons"] = [validation["blocking_reason"]]
        return report
    report["completed_stages"].append("EE_CONTRACT")

    simulation = load_simulator_module().run_document(document)
    report["simulation"] = simulation
    report["blocking_reasons"] = list(simulation["blocking_reasons"])
    report["final_state"] = simulation["final_state"]
    if not simulation["simulation_valid"]:
        return report
    report["completed_stages"].append("EE_SIM")
    report["pipeline_valid"] = True
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.out.resolve():
            raise ValueError("output_must_not_overwrite_input")
        document = json.loads(args.input.read_text(encoding="utf-8"))
        report = run_document(document)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, RuntimeError) as exc:
        report = _base_report()
        report["blocking_reasons"] = [str(exc)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pipeline_valid": report["pipeline_valid"], "final_state": report["final_state"], "blocking_reasons": report["blocking_reasons"]}, sort_keys=True))
    return 0 if report["pipeline_valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
