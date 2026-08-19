import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_CANDIDATES = (_HERE / "b5-demo-flow.py", _HERE.parent / "scripts" / "b5_demo_flow.py")
SCRIPT = next((path for path in _CANDIDATES if path.exists()), _CANDIDATES[0])
SPEC = importlib.util.spec_from_file_location("b5_demo_flow", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DemoFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "capture.bin").write_bytes(b"synthetic-camera-frame-v1")
        locked = {key: False for key in MODULE.FIXED_FALSE}
        (self.root / "vision.json").write_text(json.dumps({"schema_version": MODULE.VISION_SCHEMA, "synthetic": True, "quality_valid": True, "confidence": 0.97, "acupoints": [{"name": "demo_point", "x_norm": 0.12, "y_norm": -0.08, "z_norm": 0.31}], **locked}), encoding="utf-8")
        (self.root / "route.json").write_text(json.dumps({"schema_version": MODULE.ROUTE_SCHEMA, "synthetic": True, "valid": True, "side": "left", "non_contact_offset_norm": 0.05, "waypoints": {name: {"x_norm": 0.0, "y_norm": 0.0, "z_norm": 0.5} for name in ("safe_high", "approach_offset", "retract_offset", "return_high")}, **locked}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_nominal_flow_reaches_complete_with_locked_permissions(self):
        report = MODULE.run(self.root / "capture.bin", self.root / "vision.json", self.root / "route.json", "left")
        self.assertTrue(report["valid"])
        self.assertEqual(report["current_stage"], "COMPLETE")
        self.assertEqual(report["states"], list(MODULE.STAGES))
        self.assertEqual(report["vision"]["acupoints"][0]["name"], "demo_point")
        self.assertEqual(report["simulation"]["approach_target"]["z_norm"], 0.36)
        self.assertEqual(report["simulation"]["return_high_target"]["z_norm"], 0.5)
        self.assertFalse(report["execution_allowed"])
        self.assertFalse(report["motor_moved"])

    def test_missing_image_blocks(self):
        report = MODULE.run(self.root / "missing.bin", self.root / "vision.json", self.root / "route.json", "left")
        self.assertFalse(report["valid"])
        self.assertEqual(report["current_stage"], "BLOCKED")
        self.assertIn("image_missing", report["blocking_reasons"])

    def test_low_confidence_blocks(self):
        vision = json.loads((self.root / "vision.json").read_text())
        vision["confidence"] = 0.4
        (self.root / "vision.json").write_text(json.dumps(vision), encoding="utf-8")
        report = MODULE.run(self.root / "capture.bin", self.root / "vision.json", self.root / "route.json", "right")
        self.assertEqual(report["current_stage"], "BLOCKED")
        self.assertIn("vision_confidence_below_threshold", report["blocking_reasons"])

    def test_route_failure_and_permission_unlock_block(self):
        route = json.loads((self.root / "route.json").read_text())
        route["valid"] = False
        (self.root / "route.json").write_text(json.dumps(route), encoding="utf-8")
        report = MODULE.run(self.root / "capture.bin", self.root / "vision.json", self.root / "route.json", "left")
        self.assertEqual(report["current_stage"], "BLOCKED")
        self.assertIn("route_simulation_invalid", report["blocking_reasons"])
        vision = json.loads((self.root / "vision.json").read_text())
        vision["execution_allowed"] = True
        (self.root / "vision.json").write_text(json.dumps(vision), encoding="utf-8")
        report = MODULE.run(self.root / "capture.bin", self.root / "vision.json", self.root / "route.json", "left")
        self.assertEqual(report["current_stage"], "BLOCKED")
        self.assertIn("vision_execution_allowed_must_be_false", report["blocking_reasons"])

    def test_declared_input_hash_change_blocks(self):
        vision = json.loads((self.root / "vision.json").read_text())
        vision["image_sha256"] = "0" * 64
        (self.root / "vision.json").write_text(json.dumps(vision), encoding="utf-8")
        report = MODULE.run(self.root / "capture.bin", self.root / "vision.json", self.root / "route.json", "left")
        self.assertEqual(report["current_stage"], "BLOCKED")
        self.assertIn("image_input_hash_changed", report["blocking_reasons"])

    def test_stop_path_reaches_stopped(self):
        report = MODULE.run(self.root / "capture.bin", self.root / "vision.json", self.root / "route.json", "left", "HOLD")
        self.assertFalse(report["valid"])
        self.assertEqual(report["current_stage"], "STOPPED")
        self.assertEqual(report["states"][-1], "STOPPED")

    def test_deterministic_identity(self):
        one = MODULE.run(self.root / "capture.bin", self.root / "vision.json", self.root / "route.json", "right")
        two = MODULE.run(self.root / "capture.bin", self.root / "vision.json", self.root / "route.json", "right")
        self.assertEqual(one, two)

    def test_source_has_no_hardware_or_control_dependencies(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imports = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Call):
                calls.add(ast.unparse(node.func))
        self.assertTrue(imports.isdisjoint({"serial", "pyrealsense2", "requests", "socket", "subprocess", "multiprocessing.shared_memory"}))
        self.assertTrue(calls.isdisjoint({"open", "os.open", "requests.post", "subprocess.run", "subprocess.Popen"}))


if __name__ == "__main__":
    unittest.main()
