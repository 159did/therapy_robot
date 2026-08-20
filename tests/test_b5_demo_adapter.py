import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPT = ROOT / "scripts" / "b5_demo_adapter.py"
SPEC = importlib.util.spec_from_file_location("b5_demo_adapter", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DemoAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        locked_route = {"formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False}
        self.route = self.root / "route.json"
        self.route.write_text(json.dumps({"schema_version": "b5.m1-m2-sim.v1", "simulation_valid": True, "status": "PASS", "synthetic": True, "route_side": "left", "route_states": ["SAFE_HIGH", "LEFT_CAMERA_POSITION", "SAFE_HIGH"], "final_pose": "STOWED", "simulation_id": "b5-sim-real", "metrics": {"action_count": 5}, "blocking_reasons": [], "source": {"payload_sha256": "a" * 64}, **locked_route}), encoding="utf-8")
        self.vision = self.root / "vision.json"
        locked_vision = {"formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False}
        self.vision.write_text(json.dumps({"schema_version": "b5.vision-offline.v1", "pipeline_valid": True, "offline_simulation_valid": True, "pipeline_id": "vision-real", "hardware_access": {"d405_accessed": False, "camera_device_opened": False, "nano_accessed": False, "serial_accessed": False, "motor_command_generated": False}, "acupoints": [{"name": "大椎", "pixel": [10, 20], "valid": True, "coordinate_confidence": 0.9, "point_robot_candidate_m": [0.1, 0.2, 0.3], "simulation_endpoint_target": {"coordinate_frame": "robot_base_candidate", "position_m": [0.1, 0.2, 0.3], "executable": False}}], **locked_vision}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_left_and_right_nominal_outputs(self):
        for side in ("left", "right"):
            route = json.loads(self.route.read_text())
            route["route_side"] = side
            route["route_states"] = ["SAFE_HIGH", side.upper() + "_CAMERA_POSITION", "SAFE_HIGH"]
            self.route.write_text(json.dumps(route), encoding="utf-8")
            report = MODULE.run(self.route, self.vision, side, MODULE.file_hash(self.route), MODULE.file_hash(self.vision))
            self.assertTrue(report["valid"])
            self.assertEqual(report["current_stage"], "COMPLETE")
            self.assertEqual(report["candidate_end_effector_position_m"], [0.1, 0.2, 0.3])
            self.assertFalse(report["execution_allowed"])
            self.assertFalse(report["motor_command_generated"])

    def test_route_failure_blocks(self):
        route = json.loads(self.route.read_text())
        route["status"] = "FAIL_CLOSED"
        self.route.write_text(json.dumps(route), encoding="utf-8")
        report = MODULE.run(self.route, self.vision, "left")
        self.assertEqual(report["current_stage"], "BLOCKED")
        self.assertIn("route_simulation_failed", report["blocking_reasons"])

    def test_vision_failure_and_low_confidence_block(self):
        vision = json.loads(self.vision.read_text())
        vision["pipeline_valid"] = False
        self.vision.write_text(json.dumps(vision), encoding="utf-8")
        report = MODULE.run(self.route, self.vision, "left")
        self.assertIn("vision_pipeline_failed", report["blocking_reasons"])
        vision["pipeline_valid"] = True
        vision["acupoints"][0]["coordinate_confidence"] = 0.1
        vision["acupoints"][0]["valid"] = False
        self.vision.write_text(json.dumps(vision), encoding="utf-8")
        report = MODULE.run(self.route, self.vision, "left")
        self.assertIn("vision_no_valid_acupoint_target", report["blocking_reasons"])
        vision["acupoints"][0]["valid"] = True
        self.vision.write_text(json.dumps(vision), encoding="utf-8")
        report = MODULE.run(self.route, self.vision, "left")
        self.assertIn("vision_acupoint_0_confidence_below_threshold", report["blocking_reasons"])

    def test_missing_permission_or_hardware_field_blocks(self):
        route = json.loads(self.route.read_text())
        del route["execution_allowed"]
        self.route.write_text(json.dumps(route), encoding="utf-8")
        report = MODULE.run(self.route, self.vision, "left")
        self.assertIn("route_execution_allowed_missing", report["blocking_reasons"])
        route["execution_allowed"] = False
        self.route.write_text(json.dumps(route), encoding="utf-8")
        vision = json.loads(self.vision.read_text())
        del vision["hardware_access"]["serial_accessed"]
        self.vision.write_text(json.dumps(vision), encoding="utf-8")
        report = MODULE.run(self.route, self.vision, "left")
        self.assertIn("vision_hardware_access_not_false", report["blocking_reasons"])

    def test_hash_change_and_permission_unlock_block(self):
        report = MODULE.run(self.route, self.vision, "left", "0" * 64, MODULE.file_hash(self.vision))
        self.assertIn("route_input_hash_changed", report["blocking_reasons"])
        for source, path in (("route", self.route), ("vision", self.vision)):
            original = path.read_text(encoding="utf-8")
            for field in ("execution_allowed", "entity_action_authorized", "nano_deployment_authorized"):
                value = json.loads(original)
                value[field] = True
                path.write_text(json.dumps(value), encoding="utf-8")
                report = MODULE.run(self.route, self.vision, "left")
                self.assertIn(f"{source}_{field}_must_be_false", report["blocking_reasons"])
            path.write_text(original, encoding="utf-8")

    def test_invalid_json_blocks(self):
        self.route.write_text("{", encoding="utf-8")
        report = MODULE.run(self.route, self.vision, "left")
        self.assertEqual(report["final_state"], "BLOCKED")
        self.assertTrue(report["blocking_reasons"][0].startswith("route_json_invalid:"))

    def test_source_has_no_hardware_or_control_dependencies(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("import serial", "import socket", "subprocess", "requests", "/dev/tty", "send_position", "write_target"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
