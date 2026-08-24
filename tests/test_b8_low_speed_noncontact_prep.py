#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "b8_low_speed_noncontact_prep.py"
FIXTURE = ROOT / "docs" / "tasks" / "B8-LOW-SPEED-NONCONTACT-RECORD.example.json"
SPEC = importlib.util.spec_from_file_location("b8_prep", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class B8PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_b8_protocol_fixture.py")], check=True, cwd=ROOT)

    def value(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_protocol_fixture_is_locked_and_placeholder_only(self):
        value = self.value()
        self.assertEqual(MODULE.validate_protocol(value), value)
        self.assertTrue(value["simulation_only"])
        self.assertFalse(value["nano_tested"])
        self.assertFalse(value["arm64_tested"])
        self.assertEqual(value["entity_experiment"], "not_run")
        self.assertFalse(value["hardware_authorized"])
        self.assertFalse(value["entity_motion_authorized"])
        self.assertEqual(value["software_commit"], "9e0c4b925062b0a7c8fd2fa25fd985fe9798402b")
        self.assertEqual(value["nano_commit"], MODULE.PLACEHOLDER)
        self.assertEqual(set(value["entity_device_identity"].values()), {MODULE.PLACEHOLDER})
        self.assertEqual(value["evidence"]["raw_log_sha256"], MODULE.PLACEHOLDER)
        self.assertEqual(value["experiment_conclusion"], "NO_GO_PREPARATION_ONLY")
        self.assertEqual(set(value["future_entity_parameters"].values()), {MODULE.PLACEHOLDER})

    def test_all_required_single_step_rules_are_frozen(self):
        policy = self.value()["single_step_policy"]
        self.assertEqual(policy, MODULE.REQUIRED_POLICY)
        self.assertTrue(policy["single_axis_only"])
        self.assertTrue(policy["single_discrete_action_only"])
        self.assertTrue(policy["continuous_jog_forbidden"])
        self.assertTrue(policy["automatic_sequence_forbidden"])
        self.assertTrue(policy["human_contact_forbidden"])
        self.assertTrue(policy["dummy_contact_forbidden"])

    def test_nominal_simulation_remains_no_go_until_h1_and_arm64_evidence(self):
        result = MODULE.build_report(self.value(), "nominal")
        self.assertEqual(result["status"], "PREPARED_OFFLINE")
        self.assertFalse(result["go"])
        self.assertIn("h1_entity_readonly_pass_required", result["blocking_reasons"])
        self.assertIn("b8_safety_gate_integration_required", result["blocking_reasons"])
        self.assertIn("nano_readonly_state_required", result["blocking_reasons"])
        self.assertFalse(result["entity_motion_authorized"])
        self.assertFalse(result["motor_command_generated"])

    def test_fault_rehearsals_are_no_go_and_need_new_authorization(self):
        scenarios = ("emergency_stop", "feedback_loss", "feedback_expired", "watchdog_timeout", "soft_limit_abnormal", "collision_abnormal", "brake_unknown", "authorization_expired")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                result = MODULE.build_report(self.value(), scenario)
                self.assertEqual(result["status"], "NO_GO")
                self.assertFalse(result["go"])
                self.assertTrue(result["stop_immediately"])
                self.assertFalse(result["automatic_recovery"])
                self.assertTrue(result["recovery_requires_new_request_id"])
                self.assertTrue(result["recovery_requires_new_authorization"])

    def test_protocol_tampering_and_real_values_block(self):
        mutations = [
            lambda value: value.__setitem__("entity_motion_authorized", True),
            lambda value: value["future_entity_parameters"].__setitem__("speed", 0.001),
            lambda value: value["single_step_policy"].__setitem__("continuous_jog_forbidden", False),
            lambda value: value.__setitem__("source_sha256", "0" * 64),
            lambda value: value.__setitem__("unknown", True),
        ]
        for mutate in mutations:
            value = self.value(); mutate(value)
            with self.assertRaises(MODULE.B8Error):
                MODULE.validate_protocol(value)

    def test_non_finite_json_is_rejected(self):
        value = self.value(); value["preconditions"]["bad"] = math.nan
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nan.json"; output = Path(directory) / "report.json"
            source.write_text(json.dumps(value, allow_nan=True), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("non_finite_json_constant:NaN", json.loads(output.read_text())["blocking_reasons"])

    def test_left_right_input_stability_and_normalized_only(self):
        left = MODULE.simulate_fault("nominal"); right = MODULE.simulate_fault("nominal")
        self.assertEqual(left, right)
        encoded = json.dumps(self.value(), sort_keys=True)
        self.assertNotIn("motor_target", encoded)
        self.assertNotIn("serial_payload", encoded)
        self.assertNotIn("axis_angle", encoded)

    def test_source_has_no_hardware_or_transport_dependencies(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("import serial", "import socket", "subprocess", "shared_memory", "/dev/tty", "run-jetson", "pyrealsense", "write_serial"):
            self.assertNotIn(forbidden, source)

    def test_cli_writes_locked_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            completed = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE), "--scenario", "feedback_loss", "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "NO_GO")
            self.assertFalse(report["simulation_only"] is False)
            self.assertFalse(report["entity_motion_authorized"])
            self.assertFalse(report["native_setpoint_generated"])
            self.assertFalse(report["serial_payload_generated"])


if __name__ == "__main__":
    unittest.main()
