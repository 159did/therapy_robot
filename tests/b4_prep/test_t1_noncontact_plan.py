import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_WORKTREE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "b4_prep" / "t1_noncontact_plan.py"
SCRIPT = _WORKTREE_SCRIPT if _WORKTREE_SCRIPT.exists() else Path(__file__).resolve().parents[0] / "b4-prep-d-t1_noncontact_plan.py"


class T1NonContactPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixed = {
            "motor_command_written": False,
            "execution_allowed": False,
            "entity_action_authorized": False,
            "nano_deployment_authorized": False,
            "human_contact_allowed": False,
            "entity_camera_accessed": False,
        }
        self.plan = {
            "schema_version": "b4.prep.d.t1-plan.v1",
            "plan_id": "t1-fixture",
            "synthetic": True,
            **fixed,
            "watchdog_timeout_ms": 500,
            "phases": [
                {"phase": "NON_CONTACT_APPROACH", "synthetic": True, "distance_normalized": 0.2, "speed_normalized_per_second": 0.1, "dwell_ms": 0, "stop_conditions": ["estop", "watchdog", "approach_limit"], "operator_confirmation_required": True},
                {"phase": "HOLD", "synthetic": True, "distance_normalized": 0.0, "speed_normalized_per_second": 0.0, "dwell_ms": 1000, "stop_conditions": ["estop", "watchdog", "hold_timeout"], "operator_confirmation_required": True},
                {"phase": "RETRACT", "synthetic": True, "distance_normalized": 0.2, "speed_normalized_per_second": 0.1, "dwell_ms": 0, "stop_conditions": ["estop", "watchdog", "retract_limit"], "operator_confirmation_required": False},
            ],
            "safety": {"fail_closed": True, "estop_required": True, "watchdog_required": True},
            "rollback": {"trigger_conditions": ["any_unknown_state", "operator_abort"], "actions": ["stop_plan", "record_blocking_reason", "return_to_prepared_state"]},
        }
        (self.root / "plan.json").write_text(json.dumps(self.plan, sort_keys=True), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def run_plan(self, output):
        return subprocess.run([sys.executable, str(SCRIPT), "--plan", str(self.root / "plan.json"), "--output", str(output)], text=True, capture_output=True)

    def test_valid_plan_is_locked_and_deterministic(self):
        first, second = self.root / "one.json", self.root / "two.json"
        self.assertEqual(self.run_plan(first).returncode, 0)
        self.assertEqual(self.run_plan(second).returncode, 0)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        report = json.loads(first.read_text())
        self.assertTrue(report["valid"])
        self.assertEqual(report["phase_order"], ["NON_CONTACT_APPROACH", "HOLD", "RETRACT"])
        self.assertFalse(report["human_contact_allowed"])
        self.assertFalse(report["execution_allowed"])

    def test_phase_order_and_unknown_control_fields_fail(self):
        bad = dict(self.plan, phases=list(reversed(self.plan["phases"])))
        (self.root / "plan.json").write_text(json.dumps(bad), encoding="utf-8")
        result = self.run_plan(self.root / "bad-order.json")
        self.assertNotEqual(result.returncode, 0)
        bad = dict(self.plan, motor_target={"axis": 1})
        (self.root / "plan.json").write_text(json.dumps(bad), encoding="utf-8")
        self.assertNotEqual(self.run_plan(self.root / "bad-field.json").returncode, 0)

    def test_non_synthetic_and_nan_like_values_fail(self):
        bad = dict(self.plan, synthetic=False)
        bad["phases"] = [dict(item) for item in self.plan["phases"]]
        bad["phases"][0]["distance_normalized"] = "NaN"
        (self.root / "plan.json").write_text(json.dumps(bad), encoding="utf-8")
        self.assertNotEqual(self.run_plan(self.root / "bad-values.json").returncode, 0)


if __name__ == "__main__":
    unittest.main()
