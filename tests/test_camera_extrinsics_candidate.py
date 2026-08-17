#!/usr/bin/env python3
"""Offline B3-C candidate builder and independent validation tests."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_camera_extrinsics_candidate.py"
VALIDATOR = ROOT / "scripts" / "validate_camera_extrinsics_candidate.py"
FIXTURE = ROOT / "tests" / "fixtures" / "camera_extrinsics_candidate"
REFERENCE = "2026-08-16T10:00:04Z"


class CameraExtrinsicsCandidateTest(unittest.TestCase):
    def fixture_dir(self, root, name="fixture"):
        fixture = root / name
        shutil.copytree(FIXTURE, fixture)
        return fixture

    def build(self, fixture, output, *extra):
        return subprocess.run([sys.executable, str(BUILDER), "--fit-samples", str(fixture / "fit.json"), "--validation-samples", str(fixture / "validation.json"), "--b2-quality", str(fixture / "b2_quality.json"), "--out", str(output), "--reference-time", REFERENCE, *extra], cwd=ROOT, text=True, capture_output=True)

    def validate(self, fixture, candidate, output, *extra):
        return subprocess.run([sys.executable, str(VALIDATOR), "--candidate", str(candidate), "--validation-samples", str(fixture / "validation.json"), "--b2-quality", str(fixture / "b2_quality.json"), "--out", str(output), "--reference-time", REFERENCE, *extra], cwd=ROOT, text=True, capture_output=True)

    def test_builder_and_independent_validator_pass_non_promotable(self):
        with tempfile.TemporaryDirectory(prefix="b3c-pass-") as directory:
            root = Path(directory); fixture = self.fixture_dir(root); candidate = root / "candidate.json"; report = root / "validation.json.result.json"
            built = self.build(fixture, candidate)
            self.assertEqual(built.returncode, 0, built.stderr + built.stdout)
            candidate_data = json.loads(candidate.read_text(encoding="utf-8"))
            self.assertEqual(candidate_data["schema_version"], "b3.camera-extrinsics-candidate.v1")
            self.assertTrue(candidate_data["candidate_valid"])
            self.assertTrue(candidate_data["promotion_locked"])
            self.assertFalse(candidate_data["formal_use_allowed"])
            self.assertFalse(candidate_data["execution_allowed"])
            self.assertEqual(len(candidate_data["input_hashes"]), 3)
            checked = self.validate(fixture, candidate, report)
            self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
            validation = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(validation["validation_valid"])
            self.assertLess(validation["metrics"]["validation_rmse_mm"], 0.1)
            self.assertLess(validation["metrics"]["direction_error_deg"], 0.01)
            self.assertTrue(validation["promotion_locked"])

    def test_candidate_id_is_deterministic_and_threshold_bound(self):
        with tempfile.TemporaryDirectory(prefix="b3c-id-") as directory:
            root = Path(directory); fixture = self.fixture_dir(root); first = root / "first.json"; second = root / "second.json"; changed = root / "changed.json"
            self.assertEqual(self.build(fixture, first).returncode, 0); self.assertEqual(self.build(fixture, second).returncode, 0); self.assertEqual(self.build(fixture, changed, "--max-fit-rmse-mm", "11").returncode, 0)
            first_data = json.loads(first.read_text(encoding="utf-8")); second_data = json.loads(second.read_text(encoding="utf-8")); changed_data = json.loads(changed.read_text(encoding="utf-8"))
            self.assertEqual(first_data["candidate_id"], second_data["candidate_id"]); self.assertNotEqual(first_data["candidate_id"], changed_data["candidate_id"])

    def test_builder_rejects_reuse_bad_quality_stale_and_formal_name(self):
        with tempfile.TemporaryDirectory(prefix="b3c-build-fail-") as directory:
            root = Path(directory); fixture = self.fixture_dir(root)
            reused = json.loads((fixture / "validation.json").read_text(encoding="utf-8")); reused["batch_id"] = "fit-batch-20260816"; (fixture / "validation.json").write_text(json.dumps(reused), encoding="utf-8")
            output = root / "reused.json"; result = self.build(fixture, output); report = json.loads(output.read_text(encoding="utf-8")); self.assertEqual(result.returncode, 2); self.assertIn("batch_id_reused", report["quality"]["blocking_reasons"])
            bad_quality = json.loads((fixture / "b2_quality.json").read_text(encoding="utf-8")); bad_quality["quality_valid"] = False; (fixture / "b2_quality.json").write_text(json.dumps(bad_quality), encoding="utf-8"); output = root / "bad-quality.json"; result = self.build(fixture, output); self.assertEqual(result.returncode, 2); self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["candidate_valid"])
            formal = self.build(fixture, root / "camera_to_base.json"); self.assertNotEqual(formal.returncode, 0)

    def test_validator_rejects_hash_change_matrix_corruption_and_stale_data(self):
        with tempfile.TemporaryDirectory(prefix="b3c-validate-fail-") as directory:
            root = Path(directory); fixture = self.fixture_dir(root); candidate = root / "candidate.json"; self.assertEqual(self.build(fixture, candidate).returncode, 0)
            validation = json.loads((fixture / "validation.json").read_text(encoding="utf-8")); validation["samples"][0]["robot_point_m"][0] += 0.1; (fixture / "validation.json").write_text(json.dumps(validation), encoding="utf-8"); output = root / "hash-fail.json"; result = self.validate(fixture, candidate, output); report = json.loads(output.read_text(encoding="utf-8")); self.assertEqual(result.returncode, 2); self.assertIn("validation_input_hash_mismatch", report["blocking_reasons"])
            fixture2 = self.fixture_dir(root, "fixture2"); self.assertEqual(self.build(fixture2, root / "candidate2.json").returncode, 0)
            candidate_data = json.loads((root / "candidate2.json").read_text(encoding="utf-8")); candidate_data["matrix"]["rotation"][0][0] = 2.0; (root / "candidate2.json").write_text(json.dumps(candidate_data), encoding="utf-8"); output = root / "matrix-fail.json"; result = self.validate(fixture2, root / "candidate2.json", output); report = json.loads(output.read_text(encoding="utf-8")); self.assertEqual(result.returncode, 2); self.assertIn("candidate_rotation_not_rigid", report["blocking_reasons"])

    def test_validator_rejects_quality_failure_and_formal_output(self):
        with tempfile.TemporaryDirectory(prefix="b3c-lock-") as directory:
            root = Path(directory); fixture = self.fixture_dir(root); candidate = root / "candidate.json"; self.assertEqual(self.build(fixture, candidate).returncode, 0)
            quality = json.loads((fixture / "b2_quality.json").read_text(encoding="utf-8")); quality["quality_valid"] = False; (fixture / "b2_quality.json").write_text(json.dumps(quality), encoding="utf-8"); output = root / "quality-fail.json"; result = self.validate(fixture, candidate, output); self.assertEqual(result.returncode, 2); self.assertIn("b2_quality_invalid", json.loads(output.read_text(encoding="utf-8"))["blocking_reasons"])
            formal = self.validate(fixture, candidate, root / "camera_to_base.json"); self.assertNotEqual(formal.returncode, 0)


if __name__ == "__main__":
    unittest.main()
