#!/usr/bin/env python3
"""B2-C offline quality gate tests; no camera, serial port, or robot is used."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "evaluate_d405_quality.py"
FIXTURE = ROOT / "tests" / "fixtures" / "d405_quality" / "good.json"
REFERENCE = "2026-08-16T10:00:03Z"


def invoke(path, *extra):
    output = path.parent / (path.stem + ".result.json")
    return subprocess.run([sys.executable, str(TOOL), str(path), "--out", str(output), "--reference-time", REFERENCE, *extra], cwd=ROOT, text=True, capture_output=True), output


class D405QualityGateTest(unittest.TestCase):
    def write_input(self, root, payload):
        path = root / "input.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def base(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_good_fixture_passes_and_is_non_formal(self):
        with tempfile.TemporaryDirectory(prefix="b2c-good-") as directory:
            root = Path(directory); path = self.write_input(root, self.base())
            result, output = invoke(path)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["quality_valid"])
            self.assertFalse(report["formal_use_allowed"])
            self.assertFalse(report["execution_allowed"])
            self.assertEqual(report["schema_version"], "b2.vision-quality.v1")
            self.assertEqual(report["sample_count"], 3)
            self.assertEqual(len(report["input_hashes"]), 1)
            self.assertEqual(report["blocking_reasons"], [])

    def test_depth_ratio_failure_is_nonzero(self):
        with tempfile.TemporaryDirectory(prefix="b2c-depth-") as directory:
            root = Path(directory); payload = self.base(); payload["frames"][1]["depth_valid_ratio"] = 0.5; path = self.write_input(root, payload)
            result, output = invoke(path)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 2); self.assertFalse(report["quality_valid"]); self.assertIn("depth_valid_ratio_below_minimum", report["blocking_reasons"])

    def test_plane_failure_and_explicit_threshold(self):
        with tempfile.TemporaryDirectory(prefix="b2c-plane-") as directory:
            root = Path(directory); payload = self.base(); payload["frames"][0]["plane_rmse_m"] = 0.02; path = self.write_input(root, payload)
            result, output = invoke(path, "--max-plane-rmse-m", "0.02")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(output.read_text(encoding="utf-8")); self.assertEqual(report["thresholds"]["max_plane_rmse_m"], 0.02)
            payload["frames"][0]["plane_rmse_m"] = 0.020001; self.write_input(root, payload); result, output = invoke(path, "--max-plane-rmse-m", "0.02")
            self.assertEqual(result.returncode, 2); self.assertIn("plane_rmse_above_maximum", json.loads(output.read_text(encoding="utf-8"))["blocking_reasons"])

    def test_repeatability_failure_and_sample_shortage(self):
        with tempfile.TemporaryDirectory(prefix="b2c-repeat-") as directory:
            root = Path(directory); payload = self.base(); payload["frames"][2]["point_camera_m"] = [0.02, 0, 0.4]; path = self.write_input(root, payload)
            result, output = invoke(path); report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 2); self.assertIn("repeatability_above_maximum", report["blocking_reasons"])
            payload["frames"] = payload["frames"][:1]; self.write_input(root, payload); result, output = invoke(path); report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 2); self.assertIn("sample_count_below_minimum", report["blocking_reasons"])

    def test_timestamp_missing_stale_future_and_order(self):
        cases = [("missing", lambda p: p["frames"][1].pop("timestamp_utc"), "timestamp_missing"), ("stale", lambda p: p["frames"][1].update(timestamp_utc="2026-08-15T00:00:00Z"), "timestamp_too_old"), ("future", lambda p: p["frames"][1].update(timestamp_utc="2026-08-16T10:00:04Z"), "timestamp_in_future"), ("order", lambda p: p["frames"][1].update(timestamp_utc="2026-08-16T09:59:59Z"), "timestamp_order_invalid")]
        for name, mutate, reason in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="b2c-time-") as directory:
                root = Path(directory); payload = self.base(); mutate(payload); path = self.write_input(root, payload); result, output = invoke(path)
                report = json.loads(output.read_text(encoding="utf-8")); self.assertEqual(result.returncode, 2); self.assertIn(reason, report["blocking_reasons"])

    def test_missing_nonfinite_and_unit_errors_fail_closed(self):
        mutations = [("depth", lambda p: p["frames"][0].pop("depth_valid_ratio"), "depth_valid_ratio_missing"), ("plane", lambda p: p["frames"][0].pop("plane_rmse_m"), "plane_rmse_missing"), ("nan", lambda p: p["frames"][0].update(plane_rmse_m=float("nan")), "non_finite_plane_rmse_m"), ("range", lambda p: p["frames"][0].update(depth_valid_ratio=1.1), "depth_valid_ratio_out_of_range")]
        for name, mutate, reason in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="b2c-invalid-") as directory:
                root = Path(directory); payload = self.base(); mutate(payload); path = self.write_input(root, payload); result, output = invoke(path)
                report = json.loads(output.read_text(encoding="utf-8")); self.assertNotEqual(result.returncode, 0); self.assertFalse(report["quality_valid"])
                self.assertTrue(any(reason in item for item in report["blocking_reasons"]))

    def test_long_option_aliases_and_directory_input(self):
        with tempfile.TemporaryDirectory(prefix="b2c-alias-") as directory:
            root = Path(directory); (root / "quality_input.json").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"); output = root / "report.json"
            result = subprocess.run([sys.executable, str(TOOL), "--input", str(root), "--output", str(output), "--reference-time", REFERENCE, "--min-valid-depth-ratio", "0.9"], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout); self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["quality_valid"])

    def test_two_runs_have_identical_core_and_hash_changes(self):
        with tempfile.TemporaryDirectory(prefix="b2c-repeat-run-") as directory:
            root = Path(directory); path = self.write_input(root, self.base()); first, output = invoke(path); first_report = json.loads(output.read_text(encoding="utf-8")); first_hash = first_report["input_hashes"]
            second, output = invoke(path); second_report = json.loads(output.read_text(encoding="utf-8"));
            core = lambda report: {key: report[key] for key in ("schema_version", "quality_valid", "sample_count", "metrics", "thresholds", "checks", "blocking_reasons", "input_hashes")}
            self.assertEqual(first.returncode, second.returncode); self.assertEqual(core(first_report), core(second_report)); self.assertEqual(first_hash, second_report["input_hashes"])
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8"); third, output = invoke(path); changed = json.loads(output.read_text(encoding="utf-8")); self.assertEqual(third.returncode, 0); self.assertNotEqual(first_hash, changed["input_hashes"])


if __name__ == "__main__":
    unittest.main()
