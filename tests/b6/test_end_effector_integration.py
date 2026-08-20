#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PIPELINE_PATH = ROOT / "scripts" / "b6" / "end_effector_offline_pipeline.py"
SPEC = importlib.util.spec_from_file_location("b6_end_effector_offline_pipeline_test", PIPELINE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_contract_example() -> dict:
    path = ROOT / "docs" / "tasks" / "B6-EE-CONTRACT.examples" / "valid-command.json"
    return json.loads(path.read_text(encoding="utf-8"))


def envelope(command: dict | None = None) -> dict:
    simulator = MODULE.load_simulator_module()
    document = {
        "schema_version": "b6.ee-sim-input.v1",
        "synthetic": True,
        "side": "left",
        "scenario": "nominal",
        "command": command if command is not None else valid_contract_example(),
        "start_position_m": [0.0, 0.0, 1.60],
        "safe_high_position_m": [0.0, 0.0, 1.60],
        "simulation_config": {
            "sample_period_ms": 50,
            "hold_duration_ms": 1000,
            "stop_deceleration_m_s2": 0.10,
        },
    }
    document["input_sha256"] = simulator.content_hash(document, "input_sha256")
    return document


class EndEffectorIntegrationTests(unittest.TestCase):
    def test_canonical_contract_runs_through_locked_offline_pipeline(self):
        report = MODULE.run_document(envelope())
        self.assertTrue(report["pipeline_valid"])
        self.assertEqual(report["completed_stages"], ["SAFETY_BASELINE", "EE_CONTRACT", "EE_SIM"])
        self.assertEqual(report["final_state"], "COMPLETE")
        self.assertTrue(report["safety_decision"]["allowed"])
        self.assertFalse(report["safety_decision"]["execution_allowed"])
        self.assertTrue(report["contract_validation"]["valid"])
        for field, expected in MODULE.LOCKED_OUTPUTS.items():
            self.assertIs(report[field], expected, field)
            self.assertIs(report["simulation"][field], expected, field)

    def test_permission_unlock_is_blocked_before_simulation(self):
        command = valid_contract_example()
        command["execution_allowed"] = True
        contract = MODULE.load_contract_module()
        command["contract_sha256"] = contract.contract_hash(command)
        report = MODULE.run_document(envelope(command))
        self.assertFalse(report["pipeline_valid"])
        self.assertEqual(report["completed_stages"], ["SAFETY_BASELINE"])
        self.assertIn("execution_allowed_must_be_false", report["blocking_reasons"])
        self.assertIsNone(report["simulation"])

    def test_tampered_contract_hash_is_blocked_before_simulation(self):
        command = valid_contract_example()
        command["position_m"][0] += 0.01
        report = MODULE.run_document(envelope(command))
        self.assertFalse(report["pipeline_valid"])
        self.assertIn("contract_sha256_mismatch", report["blocking_reasons"])
        self.assertIsNone(report["simulation"])

    def test_default_safety_state_rejects_entity_control(self):
        safety = MODULE.load_safety_module()
        decision = safety.evaluate_control_request(
            safety.SafetyState.default(),
            {"action": safety.ACTION_ENTITY_CONTROL, "units": safety.NORMALIZED_UNITS},
        )
        self.assertFalse(decision.allowed)
        self.assertFalse(decision.execution_allowed)
        self.assertIn("hardware_control_mode_not_explicit", decision.reasons)
        self.assertIn("h1_status_not_pass", decision.reasons)

    def test_pipeline_source_contains_no_hardware_access(self):
        source = PIPELINE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import serial", "import socket", "import requests", "subprocess",
            "shared_memory", "pyrealsense", "/dev/tty", "send_position", "write_serial",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
