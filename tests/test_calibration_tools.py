#!/usr/bin/env python3
"""Offline B1-C checks for calibration schemas, quality gates and export refusal."""

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CAMERA_TOOL = ROOT / "scripts/calibrate_camera_to_base.py"
DEPTH_TOOL = ROOT / "scripts/calibrate_d405_depth.py"
EXPORT_TOOL = ROOT / "scripts/export_acupoints_base.py"
ANALYZE_TOOL = ROOT / "scripts/analyze_d405_sample.py"


def run_tool(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class CalibrationToolsTest(unittest.TestCase):
    def test_camera_candidate_validates_measured_fixture_and_records_hash(self):
        with tempfile.TemporaryDirectory(prefix="b1c-camera-") as directory:
            root = Path(directory)
            rotation = [[math.cos(0.2), -math.sin(0.2), 0.0], [math.sin(0.2), math.cos(0.2), 0.0], [0.0, 0.0, 1.0]]
            translation = [0.12, 0.41, 0.83]
            points = []
            for index, camera in enumerate(
                ([0.0, 0.0, 0.3], [0.1, 0.0, 0.3], [0.2, 0.0, 0.3], [0.0, 0.1, 0.35], [0.1, 0.1, 0.35], [0.2, 0.1, 0.35], [0.0, 0.2, 0.4], [0.1, 0.2, 0.4], [0.2, 0.2, 0.4])
            ):
                base = [sum(rotation[row][col] * camera[col] for col in range(3)) + translation[row] for row in range(3)]
                points.append({"name": f"m{index + 1}", "camera_point_m": camera, "robot_point_m": base})
            samples = root / "camera_samples.json"
            output = root / "camera_candidate.json"
            samples.write_text(json.dumps({"schema_version": 1, "dataset_kind": "measurement_candidate", "samples": points}), encoding="utf-8")
            result = run_tool(CAMERA_TOOL, "--samples", str(samples), "--out", str(output))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["calibration_valid"])
            self.assertFalse(report["formal_use_allowed"])
            self.assertEqual(report["point_count"], 9)
            self.assertEqual(len(report["source"]["sha256"]), 64)
            self.assertEqual(report["quality"]["blocking_reasons"], [])

    def test_camera_example_and_formal_output_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="b1c-camera-invalid-") as directory:
            root = Path(directory)
            samples = root / "camera_samples.json"
            output = root / "candidate.json"
            samples.write_text(json.dumps({"dataset_kind": "example", "samples": [
                {"name": "p1", "camera_point_m": [0, 0, 0.4], "robot_point_m": [0.1, 0.2, 0.3]},
                {"name": "p2", "camera_point_m": [0.1, 0, 0.4], "robot_point_m": [0.2, 0.2, 0.3]},
                {"name": "p3", "camera_point_m": [0, 0.1, 0.4], "robot_point_m": [0.1, 0.3, 0.3]},
            ]}), encoding="utf-8")
            result = run_tool(CAMERA_TOOL, "--samples", str(samples), "--out", str(output))
            self.assertEqual(result.returncode, 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["calibration_valid"])
            self.assertIn("dataset_is_measurement_candidate", report["quality"]["blocking_reasons"])
            formal = run_tool(CAMERA_TOOL, "--samples", str(samples), "--out", str(root / "camera_to_base.json"))
            self.assertNotEqual(formal.returncode, 0)

    def test_depth_candidate_validates_measured_fixture_and_rejects_flat_input(self):
        with tempfile.TemporaryDirectory(prefix="b1c-depth-") as directory:
            root = Path(directory)
            samples = root / "depth_samples.json"
            output = root / "depth_candidate.json"
            samples.write_text(json.dumps({"schema_version": 1, "dataset_kind": "measurement_candidate", "samples": [
                {"name": f"z{index}", "measured_z_m": value, "actual_z_m": value * 1.002 + 0.001}
                for index, value in enumerate((0.25, 0.35, 0.45, 0.55, 0.65))
            ]}), encoding="utf-8")
            result = run_tool(DEPTH_TOOL, "--samples", str(samples), "--out", str(output))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["calibration_valid"])
            self.assertEqual(report["quality"]["blocking_reasons"], [])

            flat = root / "flat.json"
            flat.write_text(json.dumps({"dataset_kind": "measurement_candidate", "samples": [
                {"name": "a", "measured_z_m": 0.4, "actual_z_m": 0.4},
                {"name": "b", "measured_z_m": 0.4, "actual_z_m": 0.41},
            ]}), encoding="utf-8")
            flat_result = run_tool(DEPTH_TOOL, "--samples", str(flat), "--out", str(root / "flat_output.json"))
            self.assertNotEqual(flat_result.returncode, 0)

    def test_export_fails_closed_without_valid_extrinsics(self):
        with tempfile.TemporaryDirectory(prefix="b1c-export-") as directory:
            root = Path(directory)
            analysis = root / "analysis.json"
            output = root / "export.json"
            analysis.write_text(json.dumps({
                "schema_version": 1,
                "quality": {"analysis_valid": True},
                "template_acupoints": [{"name": "p", "ok": True, "valid": 200, "residual_median_mm": 1.0, "point_camera_m": [0, 0, 0.4], "normal_camera": [0, 0, 1]}],
            }), encoding="utf-8")
            result = run_tool(EXPORT_TOOL, "--result", str(analysis), "--extrinsics", str(root / "missing.json"), "--out", str(output))
            self.assertEqual(result.returncode, 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["calibration_valid"])
            self.assertFalse(report["execution_allowed"])
            self.assertEqual(report["count"], 0)

    def test_export_transforms_only_quality_checked_points(self):
        with tempfile.TemporaryDirectory(prefix="b1c-export-valid-") as directory:
            root = Path(directory)
            analysis = root / "analysis.json"
            extrinsics = root / "candidate.json"
            output = root / "export.json"
            analysis.write_text(json.dumps({
                "schema_version": 1,
                "quality": {"analysis_valid": True},
                "template_acupoints": [{"name": "p", "ok": True, "valid": 200, "residual_median_mm": 1.0, "point_camera_m": [0, 0, 0.4], "normal_camera": [0, 0, 1]}],
            }), encoding="utf-8")
            extrinsics.write_text(json.dumps({
                "type": "camera_to_robot_base_rigid_transform",
                "schema_version": 1,
                "calibration_valid": True,
                "rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "translation_m": [0.1, 0.2, 0.3],
                "rmse_mm": 1.0,
            }), encoding="utf-8")
            result = run_tool(EXPORT_TOOL, "--result", str(analysis), "--extrinsics", str(extrinsics), "--out", str(output))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["calibration_valid"])
            self.assertTrue(report["quality_valid"])
            self.assertFalse(report["execution_allowed"])
            self.assertEqual(report["acupoints"][0]["point_base_mm"], [100.0, 200.0, 700.0])

    def test_analyzer_declares_offline_quality_contract(self):
        text = ANALYZE_TOOL.read_text(encoding="utf-8")
        for fragment in ("schema_version", "input_manifest", "analysis_valid", "execution_allowed", "--output-dir", "derived/analysis-b1c"):
            self.assertIn(fragment, text)
        self.assertIn("raise SystemExit(main())", text)


if __name__ == "__main__":
    unittest.main()
