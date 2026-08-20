import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "b5_offline_demo.py"
SPEC = importlib.util.spec_from_file_location("b5_offline_demo", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class OfflineDemoTests(unittest.TestCase):
    def test_left_and_right_use_integrated_outputs(self):
        for side in ("left", "right"):
            report = MODULE.run_demo(side)
            self.assertTrue(report["valid"])
            self.assertEqual(report["current_stage"], "COMPLETE")
            self.assertEqual(report["side"], side)
            self.assertFalse(report["execution_allowed"])
            self.assertFalse(report["orchestration"]["producer_invoked"])
            self.assertFalse(report["orchestration"]["hardware_accessed"])

    def test_hash_mismatch_blocks(self):
        route = MODULE.DEFAULT_ROUTES["left"]
        report = MODULE.run_demo("left", expected_route_sha256="0" * 64)
        self.assertFalse(report["valid"])
        self.assertIn("route_input_hash_changed", report["blocking_reasons"])

    def test_missing_input_blocks_without_hardware(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.json"
            report = MODULE.run_demo("left", route=missing)
        self.assertFalse(report["valid"])
        self.assertEqual(report["current_stage"], "BLOCKED")
        self.assertFalse(report["orchestration"]["hardware_accessed"])

    def test_source_has_no_runtime_dependencies(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("import serial", "import socket", "subprocess", "requests", "/dev/tty", "send_position", "write_target"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
