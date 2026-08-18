import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_CANDIDATES = (
    _HERE / "build_safety_package.py",
    _HERE.parents[1] / "scripts" / "b4_prep" / "build_safety_package.py",
    _HERE / "b4-prep-d-build_safety_package.py",
)
SCRIPT = next((candidate for candidate in _CANDIDATES if candidate.exists()), _CANDIDATES[0])


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


class SafetyPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixed = {"execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False, "formal_use_allowed": False, "human_contact_allowed": False, "entity_camera_accessed": False}
        write(self.root / "promotion.json", {"schema_version": "b4.prep.d.v2f-promotion-gate.v1", "valid": True, "promotion_locked": True, **fixed, "candidate_summary": {}, "promotion_gate": {"blocking_reasons": []}})
        write(self.root / "t1.json", {"schema_version": "b4.prep.d.t1-plan-report.v1", "valid": True, "promotion_locked": True, "synthetic": True, "phase_order": ["NON_CONTACT_APPROACH", "HOLD", "RETRACT"], **fixed})
        write(self.root / "risk.json", {"schema_version": "b4.prep.d.risk-register.v1", "risks": [{"id": "R01", "hazard": "unknown_state", "trigger": "unknown", "mitigation": "stop", "residual_risk": "blocking", "blocking": True}]})
        write(self.root / "checklist.json", {"schema_version": "b4.prep.d.operator-checklist.v1", "preflight": ["verify authorization"], "in_progress": ["monitor stop conditions"], "postflight": ["preserve evidence"], "operator_confirmed": False})
        write(self.root / "template.json", {"schema_version": "b4.prep.d.report-template.v1", "required_fields": ["package_id", "promotion_gate", "t1_plan", "events", "evidence_hashes", "blocking_reasons", "entity_access_declaration"]})

    def tearDown(self):
        self.temp.cleanup()

    def run_package(self, output):
        args = [sys.executable, str(SCRIPT), "--promotion-gate", str(self.root / "promotion.json"), "--t1-plan", str(self.root / "t1.json"), "--risk-register", str(self.root / "risk.json"), "--operator-checklist", str(self.root / "checklist.json"), "--report-template", str(self.root / "template.json"), "--output", str(output)]
        return subprocess.run(args, text=True, capture_output=True)

    def test_valid_package_is_deterministic_and_non_authorizing(self):
        one, two = self.root / "one.json", self.root / "two.json"
        self.assertEqual(self.run_package(one).returncode, 0)
        self.assertEqual(self.run_package(two).returncode, 0)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        package = json.loads(one.read_text())
        self.assertTrue(package["valid"])
        self.assertFalse(package["formal_use_allowed"])
        self.assertFalse(package["human_contact_allowed"])
        self.assertIn("independent_authorization", " ".join(package["blocking_reasons"]))
        self.assertNotIn(str(self.root), one.read_text())

    def test_operator_confirmation_and_risk_unlock_are_rejected(self):
        checklist = json.loads((self.root / "checklist.json").read_text())
        checklist["operator_confirmed"] = True
        write(self.root / "checklist.json", checklist)
        output = self.root / "bad-checklist.json"
        self.assertNotEqual(self.run_package(output).returncode, 0)
        risk = json.loads((self.root / "risk.json").read_text())
        risk["risks"][0]["blocking"] = False
        write(self.root / "risk.json", risk)
        output = self.root / "bad-risk.json"
        self.assertNotEqual(self.run_package(output).returncode, 0)
        report = json.loads(output.read_text())
        self.assertFalse(report["valid"])
        self.assertFalse(report["execution_allowed"])


if __name__ == "__main__":
    unittest.main()
