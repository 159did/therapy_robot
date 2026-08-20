#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "b6_ee_sim.py"
SPEC = importlib.util.spec_from_file_location("b6_ee_sim", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_command(side: str = "left") -> dict:
    command = {
        "schema_version": "b6.end-effector-command.v1",
        "command_id": f"ee-{side}-0001",
        "sequence": 1,
        "created_at": "2026-08-20T04:00:00Z",
        "source": "offline_vision",
        "idempotency_key": f"ee-{side}-0001-v1",
        "coordinate_frame": "robot_base_candidate",
        "position_m": [0.1609163182 if side == "left" else -0.1609163182, 0.1728330895, 1.2935009363],
        "orientation_policy": "keep_current",
        "target_kind": "offline_simulation_only",
        "executable": False,
        "max_speed": {"value": 0.02, "unit": "m/s"},
        "max_acceleration": {"value": 0.10, "unit": "m/s^2"},
        "max_jerk": {"supported": False, "value": None, "unit": "unsupported"},
        "timeout_ms": 120000,
        "approach_offset_m": [0.0, 0.0, 0.05],
        "retract_offset_m": [0.0, 0.0, 0.08],
        "simulation_only": True,
        "formal_use_allowed": False,
        "promotion_locked": True,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "h1_required": True,
        "feedback_required": True,
        "emergency_stop_required_clear": True,
        "collision_check_required": True,
        "status": "APPROACH",
    }
    command["contract_sha256"] = MODULE.content_hash(command, "contract_sha256")
    return command


def make_input(side: str = "left", scenario: str = "nominal") -> dict:
    document = {
        "schema_version": "b6.ee-sim-input.v1",
        "synthetic": True,
        "side": side,
        "scenario": scenario,
        "command": make_command(side),
        "start_position_m": [0.0, 0.0, 1.60],
        "safe_high_position_m": [0.0, 0.0, 1.60],
        "simulation_config": {
            "sample_period_ms": 50,
            "hold_duration_ms": 1000,
            "stop_deceleration_m_s2": 0.10,
        },
    }
    document["input_sha256"] = MODULE.content_hash(document, "input_sha256")
    return document


def resign(document: dict) -> dict:
    document["command"]["contract_sha256"] = MODULE.content_hash(document["command"], "contract_sha256")
    document["input_sha256"] = MODULE.content_hash(document, "input_sha256")
    return document


class EndEffectorSimulationTests(unittest.TestCase):
    def test_left_and_right_targets_complete_and_return_high(self):
        expected = list(MODULE.NORMAL_STATES)
        for side in ("left", "right"):
            with self.subTest(side=side):
                report = MODULE.run_document(make_input(side))
                self.assertTrue(report["simulation_valid"])
                self.assertEqual(report["final_state"], "COMPLETE")
                self.assertEqual([item["state"] for item in report["states"]], expected)
                self.assertEqual(report["states"][-1]["simulated_position_m"], [0.0, 0.0, 1.60])
                self.assertEqual([item["step"] for item in report["states"]], list(range(7)))
                self.assertEqual(report["states"], sorted(report["states"], key=lambda item: item["timestamp_ms"]))
                self.assertEqual(report["metrics"]["trajectory_point_count"], 7)

    def test_non_contact_offset_missing_blocks(self):
        document = make_input()
        del document["command"]["approach_offset_m"]
        document["input_sha256"] = MODULE.content_hash(document, "input_sha256")
        report = MODULE.run_document(document)
        self.assertFalse(report["simulation_valid"])
        self.assertIn("missing_fields:approach_offset_m", report["blocking_reasons"])

    def test_target_out_of_workspace_blocks(self):
        document = make_input()
        document["command"]["position_m"] = [0.70, 0.0, 1.0]
        report = MODULE.run_document(resign(document))
        self.assertFalse(report["simulation_valid"])
        self.assertIn("position_x_outside_workspace", report["blocking_reasons"])

    def test_maximum_speed_violation_blocks(self):
        document = make_input()
        document["command"]["max_speed"]["value"] = 0.051
        report = MODULE.run_document(resign(document))
        self.assertIn("max_speed_exceeds_experimental_limit", report["blocking_reasons"])
        self.assertEqual(report["final_state"], "BLOCKED")

    def test_maximum_acceleration_violation_blocks(self):
        document = make_input()
        document["command"]["max_acceleration"]["value"] = 0.201
        report = MODULE.run_document(resign(document))
        self.assertIn("max_acceleration_exceeds_experimental_limit", report["blocking_reasons"])

    def test_insufficient_stopping_distance_blocks(self):
        document = make_input()
        document["simulation_config"]["stop_deceleration_m_s2"] = 0.001
        report = MODULE.run_document(resign(document))
        self.assertFalse(report["simulation_valid"])
        self.assertIn("stopping_distance_insufficient", report["blocking_reasons"])
        self.assertEqual(report["final_state"], "BLOCKED")

    def test_operator_and_feedback_stop_flows(self):
        for scenario in ("operator_stop", "feedback_stale"):
            with self.subTest(scenario=scenario):
                report = MODULE.run_document(make_input(scenario=scenario))
                self.assertTrue(report["simulation_valid"])
                self.assertEqual(report["final_state"], "STOPPED")
                self.assertIn(scenario, report["blocking_reasons"])

    def test_b4_emergency_watchdog_and_feedback_loss_stop_flows(self):
        b4 = MODULE.load_b4_module()
        self.assertEqual(b4.TOOL_VERSION, "b4-prep-c.1")
        for scenario in ("emergency_stop", "watchdog_timeout", "feedback_loss"):
            with self.subTest(scenario=scenario):
                report = MODULE.run_document(make_input(scenario=scenario))
                self.assertTrue(report["simulation_valid"])
                self.assertEqual(report["final_state"], "STOPPED")
                self.assertIn(scenario, report["blocking_reasons"])
                self.assertEqual([item["event"] for item in report["safety_model"]["fault_events"]], ["stop_requested", "stopping", "stopped"])

    def test_soft_limit_violation_stops(self):
        document = make_input()
        document["command"]["position_m"] = [0.58, 0.0, 1.0]
        report = MODULE.run_document(resign(document))
        self.assertTrue(report["simulation_valid"])
        self.assertEqual(report["final_state"], "STOPPED")
        self.assertIn("soft_limit_violation", report["blocking_reasons"])

    def test_collision_boundary_stops(self):
        document = make_input()
        document["command"]["position_m"] = [0.0, 0.20, 0.50]
        report = MODULE.run_document(resign(document))
        self.assertTrue(report["simulation_valid"])
        self.assertEqual(report["final_state"], "STOPPED")
        self.assertIn("collision_detected", report["blocking_reasons"])
        self.assertLess(report["metrics"]["minimum_clearance_m"], 0.0)

    def test_explicit_target_out_of_workspace_scenario_blocks(self):
        report = MODULE.run_document(make_input(scenario="target_out_of_workspace"))
        self.assertFalse(report["simulation_valid"])
        self.assertEqual(report["final_state"], "BLOCKED")

    def test_simulation_id_is_deterministic_and_input_sensitive(self):
        first = MODULE.run_document(make_input())
        second = MODULE.run_document(make_input())
        self.assertEqual(first["simulation_id"], second["simulation_id"])
        changed = make_input()
        changed["command"]["command_id"] = "ee-left-0002"
        changed["command"]["idempotency_key"] = "ee-left-0002-v1"
        third = MODULE.run_document(resign(changed))
        self.assertNotEqual(first["simulation_id"], third["simulation_id"])

    def test_contract_and_envelope_hash_changes_block(self):
        contract_changed = make_input()
        contract_changed["command"]["position_m"][0] += 0.01
        contract_changed["input_sha256"] = MODULE.content_hash(contract_changed, "input_sha256")
        self.assertIn("contract_sha256_mismatch", MODULE.run_document(contract_changed)["blocking_reasons"])
        input_changed = make_input()
        input_changed["side"] = "right"
        self.assertIn("input_sha256_mismatch", MODULE.run_document(input_changed)["blocking_reasons"])

    def test_all_permission_outputs_remain_false(self):
        fields = (
            "formal_use_allowed", "execution_allowed", "entity_action_authorized",
            "nano_deployment_authorized", "motor_command_generated", "motor_target_generated",
            "serial_payload_generated",
        )
        reports = [
            MODULE.run_document(make_input()),
            MODULE.run_document(make_input(scenario="emergency_stop")),
            MODULE.run_document({}),
        ]
        for report in reports:
            for field in fields:
                self.assertIs(report[field], False, field)
        for field, unsafe in (("execution_allowed", True), ("entity_action_authorized", True), ("formal_use_allowed", True)):
            document = make_input()
            document["command"][field] = unsafe
            report = MODULE.run_document(resign(document))
            self.assertIn(f"{field}_must_be_false", report["blocking_reasons"])

    def test_trajectory_respects_reported_speed_and_non_contact_offset(self):
        report = MODULE.run_document(make_input())
        speed_limit = report["metrics"]["maximum_speed_m_s"]
        for point in report["states"]:
            speed = MODULE.norm(point["simulated_velocity_m_s"])
            self.assertLessEqual(speed, speed_limit + 1e-12)
        approach = next(item for item in report["states"] if item["state"] == "APPROACH")
        self.assertAlmostEqual(approach["distance_to_target_m"], 0.05)

    def test_cli_invalid_json_is_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="b6-ee-sim-") as directory:
            root = Path(directory)
            source, output = root / "invalid.json", root / "result.json"
            source.write_text("{", encoding="utf-8")
            completed = subprocess.run([sys.executable, str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 2)
            self.assertFalse(report["simulation_valid"])
            self.assertEqual(report["final_state"], "BLOCKED")
            self.assertFalse(report["motor_command_generated"])

    def test_source_has_no_hardware_control_or_motor_target_output(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "import serial", "import socket", "import requests", "subprocess", "shared_memory",
            "pyrealsense", "/dev/tty", "write_serial", "send_position", "motor_axis",
            '"G0"', '"G1"', '"G2"',
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("m1_m2_motion_sim.py", source)


if __name__ == "__main__":
    unittest.main()
