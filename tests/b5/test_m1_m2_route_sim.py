#!/usr/bin/env python3
"""B5 simplified M1/M2 software-only route tests."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "b5" / "m1_m2_route_sim.py"
SCHEMA = ROOT / "scripts" / "b5" / "m1_m2_route.schema.json"
B4_FIXTURE = ROOT / "tests" / "b4_prep" / "fixtures" / "m1_m2_motion" / "nominal.json"
SPEC = importlib.util.spec_from_file_location("b5_m1_m2_route_sim", SCRIPT)
assert SPEC and SPEC.loader
SIM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIM)


class SimplifiedRouteTests(unittest.TestCase):
    def b4_input(self) -> dict:
        return json.loads(B4_FIXTURE.read_text(encoding="utf-8"))

    def document(self, side: str = "left", scenario: str = "nominal", mutate=None) -> dict:
        nested = self.b4_input()
        if mutate:
            mutate(nested)
        nested["payload_sha256"] = SIM.load_b4_module().payload_sha256(nested)
        document = {
            "schema_version": "b5.m1-m2-sim-input.v1",
            "synthetic": True,
            "source": {"kind": "synthetic_fixture", "fixture_id": f"b5-{side}-{scenario}"},
            "route_side": side,
            "scenario": scenario,
            "b4_input": nested,
        }
        document["payload_sha256"] = SIM.payload_sha256(document)
        return document

    def run_document(self, document: dict):
        with tempfile.TemporaryDirectory(prefix="b5-m1-m2-") as directory:
            root = Path(directory)
            source = root / "input.json"
            output = root / "result.json"
            source.write_text(json.dumps(document, allow_nan=True), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, check=False, capture_output=True, text=True)
            return completed, json.loads(output.read_text(encoding="utf-8"))

    def test_left_and_right_nominal_routes_use_three_states(self) -> None:
        for side, expected in (("left", "LEFT_CAMERA_POSITION"), ("right", "RIGHT_CAMERA_POSITION")):
            with self.subTest(side=side):
                completed, result = self.run_document(self.document(side))
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertTrue(result["simulation_valid"])
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["route_states"], ["SAFE_HIGH", expected, "SAFE_HIGH"])
                self.assertEqual(result["final_pose"], "STOWED")
                self.assertEqual(result["metrics"]["action_count"], 5)
                self.assertGreaterEqual(result["metrics"]["minimum_speed_norm_s"], 0.1)
                self.assertGreaterEqual(result["metrics"]["minimum_displacement_norm"], 0.05)
                self.assertGreater(result["metrics"]["max_stop_distance_norm"], 0.0)
                self.assertTrue(result["checks"]["route_returns_safe_high"])
                self.assertTrue(result["promotion_locked"])
                self.assertFalse(result["formal_use_allowed"])
                self.assertFalse(result["execution_allowed"])
                self.assertFalse(result["entity_action_authorized"])
                self.assertFalse(result["nano_deployment_authorized"])

    def test_same_conditions_are_stable_for_each_side(self) -> None:
        for side in ("left", "right"):
            first, first_report = self.run_document(self.document(side))
            second, second_report = self.run_document(self.document(side))
            self.assertEqual(first.returncode, second.returncode)
            self.assertEqual(first_report, second_report)

    def test_emergency_watchdog_and_feedback_loss_fail_closed_on_both_sides(self) -> None:
        for side in ("left", "right"):
            for scenario in ("emergency_stop", "watchdog_timeout", "feedback_loss"):
                with self.subTest(side=side, scenario=scenario):
                    completed, result = self.run_document(self.document(side, scenario))
                    self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                    self.assertTrue(result["simulation_valid"])
                    self.assertEqual(result["status"], "FAIL_CLOSED")
                    self.assertEqual(result["route_states"], ["SAFE_HIGH"])
                    self.assertEqual(result["final_pose"], "STOPPED")
                    self.assertTrue(result["checks"]["fault_fail_closed"])
                    self.assertTrue(result["blocking_reasons"])
                    self.assertFalse(result["execution_allowed"])
                    self.assertFalse(result["entity_action_authorized"])

    def test_low_speed_and_displacement_are_blocked(self) -> None:
        mutations = (
            lambda nested: nested["segments"][0]["actions"][0].__setitem__("speed_norm_s", 0.01),
            lambda nested: nested["segments"][0]["actions"][0].__setitem__("distance_norm", 0.01),
        )
        for mutate in mutations:
            completed, result = self.run_document(self.document("left", mutate=mutate))
            self.assertEqual(completed.returncode, 2)
            self.assertFalse(result["simulation_valid"])
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(result["promotion_locked"])
            self.assertFalse(result["execution_allowed"])

    def test_payload_tampering_is_blocked(self) -> None:
        document = self.document("right")
        document["b4_input"]["scenario"] = "feedback_loss"
        completed, result = self.run_document(document)
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(result["simulation_valid"])
        self.assertIn("payload_sha256_mismatch", result["blocking_reasons"])

    def test_schema_and_source_remain_offline_only(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("import serial", "import socket", "subprocess", "shared_memory", "/dev/tty", "write_target", "send_position"):
            self.assertNotIn(forbidden, source)
        self.assertIn("SAFE_HIGH", source)
        self.assertIn("LEFT_CAMERA_POSITION", source)
        self.assertIn("RIGHT_CAMERA_POSITION", source)


if __name__ == "__main__":
    unittest.main()
