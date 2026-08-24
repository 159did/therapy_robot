import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("observation_flow", ROOT / "scripts" / "observation_flow.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ObservationFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.route = ROOT / "docs/progress/evidence/B5/DEMO/route-left-from-b5-m1-m2.json"
        self.vision = ROOT / "docs/progress/evidence/B5/DEMO/vision-from-b5-vision.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_flow_is_detailed_and_locked(self):
        report = MODULE.run(self.route, self.vision, "left")
        self.assertTrue(report["valid"])
        self.assertEqual(report["states"], list(MODULE.STAGES))
        self.assertEqual(report["current_stage"], "COMPLETE")
        self.assertEqual(report["stage_details"][2]["detail"]["side"], "left")
        self.assertGreater(report["stage_details"][5]["detail"]["count"], 0)
        self.assertEqual(report["candidate_hover_position_m"], [0.1609163181992805, 0.1728330895391088, 1.2935009362530452])
        self.assertFalse(report["execution_allowed"])
        self.assertFalse(report["motor_moved"])

    def test_missing_fixture_blocks(self):
        report = MODULE.run(self.root / "missing.json", self.vision, "left")
        self.assertFalse(report["valid"])
        self.assertEqual(report["current_stage"], "BLOCKED")

    def test_source_has_no_device_or_control_import(self):
        source = (ROOT / "scripts/observation_flow.py").read_text(encoding="utf-8")
        for forbidden in ("import serial", "pyrealsense2", "import requests", "subprocess", "/dev/tty", "import socket"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
