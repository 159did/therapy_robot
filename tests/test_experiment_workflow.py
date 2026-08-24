import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("experiment_workflow", ROOT / "scripts" / "experiment_workflow.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExperimentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.route = ROOT / "docs/progress/evidence/B5/DEMO/route-right-from-b5-m1-m2.json"
        self.vision = ROOT / "docs/progress/evidence/B5/DEMO/vision-from-b5-vision.json"

    def test_offline_complete_flow_is_locked(self):
        report = MODULE.run(self.route, self.vision, "right")
        self.assertTrue(report["valid"], report["blocking_reasons"])
        self.assertEqual(report["states"], list(MODULE.STAGES))
        self.assertFalse(report["execution_allowed"])
        self.assertFalse(report["motor_command_generated"])
        self.assertFalse(report["entity_d405_accessed"])
        self.assertFalse(report["stage_details"][7]["detail"]["contact"])

    def test_hardware_mode_is_explicitly_blocked(self):
        report = MODULE.run(self.route, self.vision, "right", "hardware")
        self.assertFalse(report["valid"])
        self.assertIn("requires_h1", report["blocking_reasons"][0])


if __name__ == "__main__":
    unittest.main()
