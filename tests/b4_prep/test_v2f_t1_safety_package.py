#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_WORKTREE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "b4_prep" / "v2f_t1_safety_package.py"
SCRIPT = _WORKTREE_SCRIPT if _WORKTREE_SCRIPT.exists() else Path(__file__).resolve().parents[0] / "b4-prep-d-v2f_t1_safety_package.py"
SPEC = importlib.util.spec_from_file_location("b4_prep_d_gate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class V2FT1SafetyPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fit = {
            "schema_version": "b3.camera-samples.v1",
            "dataset_kind": "measurement_candidate",
            "batch_id": "fit-batch",
            "coordinate_frames": {"source": "d405_camera", "target": "robot_base"},
            "units": {"points": "m"},
            "samples": [{"sample_id": "fit-01", "timestamp_utc": "2026-08-18T00:00:00Z", "camera_point_m": [0.0, 0.0, 0.0], "robot_point_m": [0.0, 0.0, 0.0]}],
        }
        self.validation = {
            "schema_version": "b3.camera-samples.v1",
            "dataset_kind": "measurement_candidate",
            "batch_id": "validation-batch",
            "coordinate_frames": {"source": "d405_camera", "target": "robot_base"},
            "units": {"points": "m"},
            "samples": [{"sample_id": "validation-01", "timestamp_utc": "2026-08-18T00:00:01Z", "camera_point_m": [0.1, 0.0, 0.0], "robot_point_m": [0.1, 0.0, 0.0]}],
        }
        self.quality = {
            "schema_version": "b2.vision-quality.v1",
            "quality_valid": True,
            "formal_use_allowed": False,
            "execution_allowed": False,
            "blocking_reasons": [],
            "checks": [{"id": "offline", "status": "pass"}],
        }
        write_json(self.root / "fit.json", self.fit)
        write_json(self.root / "validation.json", self.validation)
        write_json(self.root / "quality.json", self.quality)
        fit_hash = hashlib.sha256((self.root / "fit.json").read_bytes()).hexdigest()
        validation_hash = hashlib.sha256((self.root / "validation.json").read_bytes()).hexdigest()
        quality_hash = hashlib.sha256((self.root / "quality.json").read_bytes()).hexdigest()
        self.candidate = {
            "schema_version": "b3.camera-extrinsics-candidate.v1",
            "candidate_id": "camcand-fixture",
            "candidate_valid": True,
            "formal_use_allowed": False,
            "promotion_locked": True,
            "execution_allowed": False,
            "entity_action_authorized": False,
            "nano_deployment_authorized": False,
            "fit_input": {"sha256": fit_hash, "batch_id": "fit-batch", "sample_ids": ["fit-01"]},
            "validation_input": {"sha256": validation_hash, "batch_id": "validation-batch"},
            "quality_binding": {"sha256": quality_hash, "schema_version": "b2.vision-quality.v1"},
        }
        write_json(self.root / "candidate.json", self.candidate)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def command(self, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run([
            sys.executable, str(SCRIPT), "--candidate", str(self.root / "candidate.json"),
            "--fit-input", str(self.root / "fit.json"), "--validation-input", str(self.root / "validation.json"),
            "--quality-report", str(self.root / "quality.json"), "--reference-time", "2026-08-18T00:00:10Z",
            "--output", str(output),
        ], text=True, capture_output=True)

    def test_valid_gate_is_deterministic_and_locked(self) -> None:
        first = self.root / "first.json"
        second = self.root / "second.json"
        one = self.command(first)
        two = self.command(second)
        self.assertEqual(one.returncode, 0, one.stderr)
        self.assertEqual(two.returncode, 0, two.stderr)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        report = json.loads(first.read_text(encoding="utf-8"))
        self.assertTrue(report["valid"])
        self.assertTrue(report["promotion_locked"])
        self.assertFalse(report["formal_use_allowed"])
        self.assertFalse(report["execution_allowed"])
        self.assertNotIn(str(self.root), first.read_text(encoding="utf-8"))

    def test_tampered_validation_hash_is_invalid(self) -> None:
        data = json.loads((self.root / "validation.json").read_text(encoding="utf-8"))
        data["samples"][0]["robot_point_m"][0] = 0.2
        write_json(self.root / "validation.json", data)
        output = self.root / "invalid.json"
        result = self.command(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["valid"])
        self.assertIn("validation_input_hash_mismatch", result.stderr)

    def test_dataset_reuse_and_old_timestamp_are_blocking(self) -> None:
        validation = dict(self.validation, batch_id="fit-batch")
        write_json(self.root / "validation.json", validation)
        validation_hash = hashlib.sha256((self.root / "validation.json").read_bytes()).hexdigest()
        candidate = dict(self.candidate)
        candidate["validation_input"] = {"sha256": validation_hash, "batch_id": "fit-batch"}
        write_json(self.root / "candidate.json", candidate)
        output = self.root / "reuse.json"
        result = self.command(output)
        self.assertNotEqual(result.returncode, 0)
        reasons = json.loads(output.read_text(encoding="utf-8"))["promotion_gate"]["blocking_reasons"]
        self.assertIn("batch_id_reused", reasons)

        data = dict(self.validation)
        data["samples"][0]["timestamp_utc"] = "2020-01-01T00:00:00Z"
        write_json(self.root / "validation.json", data)
        validation_hash = hashlib.sha256((self.root / "validation.json").read_bytes()).hexdigest()
        candidate["validation_input"] = {"sha256": validation_hash, "batch_id": "validation-batch"}
        write_json(self.root / "candidate.json", candidate)
        old = self.root / "old.json"
        result = self.command(old)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(old.read_text(encoding="utf-8"))["valid"])

    def test_permission_field_and_unknown_candidate_schema_fail(self) -> None:
        candidate = dict(self.candidate, execution_allowed=True)
        write_json(self.root / "candidate.json", candidate)
        output = self.root / "permission.json"
        self.assertNotEqual(self.command(output).returncode, 0)
        candidate = dict(self.candidate, schema_version="b3.camera-extrinsics-candidate.v0")
        write_json(self.root / "candidate.json", candidate)
        output = self.root / "schema.json"
        self.assertNotEqual(self.command(output).returncode, 0)


if __name__ == "__main__":
    unittest.main()
