#!/usr/bin/env python3
"""Tests for the offline-only paper result builder."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_offline_vision_paper_results.py"


def report(valid: bool, low_confidence: bool = False) -> dict:
    items = []
    for index, name in enumerate(("大椎", "肺俞-L", "肺俞-R", "心俞-L", "心俞-R", "肾俞-L", "肾俞-R")):
        items.append({
            "name": name,
            "pixel": [80 + index, 20 + index],
            "point_camera_m": [0.01, 0.02, 0.4],
            "point_robot_candidate_m": [0.1, 0.2, 0.7],
            "coordinate_confidence": 0.3 if low_confidence else 0.8,
            "valid": valid,
            "simulation_endpoint_target": ({"executable": False} if valid else None),
        })
    return {
        "pipeline_id": "fixture-valid" if valid else "fixture-blocked",
        "pipeline_valid": valid,
        "acupoint_count": 7,
        "formal_use_allowed": False,
        "promotion_locked": True,
        "execution_allowed": False,
        "hardware_access": {"d405_accessed": False, "camera_device_opened": False, "nano_accessed": False, "serial_accessed": False, "motor_command_generated": False},
        "input": {"image_sha256": "a" * 64},
        "target_region": {"bbox_px": [20, 10, 139, 109], "confidence": 0.9, "depth_coverage": 0.8, "center_depth_m": 0.4},
        "formal_blocking_reasons": ["formal_extrinsics_missing"],
        "blocking_reasons": [] if valid else ["low_confidence:大椎"],
        "acupoints": items,
    }


class PaperResultsTest(unittest.TestCase):
    def test_generates_figures_table_and_summary(self):
        with tempfile.TemporaryDirectory(prefix="b5-paper-") as directory:
            root = Path(directory)
            image = root / "rgb.png"
            Image.new("RGB", (160, 120), (125, 145, 150)).save(image)
            normal = root / "normal.json"; normal.write_text(json.dumps(report(True), ensure_ascii=False), encoding="utf-8")
            blocked = root / "blocked.json"; blocked.write_text(json.dumps(report(False, True), ensure_ascii=False), encoding="utf-8")
            out = root / "paper"
            result = subprocess.run([sys.executable, str(SCRIPT), "--image", str(image), "--normal-result", str(normal), "--blocked-result", str(blocked), "--out-dir", str(out)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = ["01_input_overview.png", "01_input_rgb.png", "02_target_region.png", "03_acupoints_annotated.png", "04_normal_vs_blocked.png", "acupoint_results.csv", "acupoint_results.md", "paper_results_summary.json"]
            self.assertEqual(sorted(path.name for path in out.iterdir()), expected)
            for name in ("01_input_overview.png", "02_target_region.png", "03_acupoints_annotated.png", "04_normal_vs_blocked.png"):
                with Image.open(out / name) as rendered:
                    self.assertGreater(rendered.width, 1000)
                    self.assertGreater(rendered.height, 700)
            with (out / "acupoint_results.csv").open(encoding="utf-8", newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 7)
            summary = json.loads((out / "paper_results_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["locks"], {"formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False})
            self.assertFalse(summary["blocked_result"]["pipeline_valid"])
            self.assertEqual(len(summary["outputs"]), 10)

    def test_rejects_unlocked_report(self):
        with tempfile.TemporaryDirectory(prefix="b5-paper-lock-") as directory:
            root = Path(directory)
            image = root / "rgb.png"; Image.new("RGB", (160, 120), (125, 145, 150)).save(image)
            normal_data = report(True); normal_data["execution_allowed"] = True
            normal = root / "normal.json"; normal.write_text(json.dumps(normal_data), encoding="utf-8")
            blocked = root / "blocked.json"; blocked.write_text(json.dumps(report(False, True)), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--image", str(image), "--normal-result", str(normal), "--blocked-result", str(blocked), "--out-dir", str(root / "paper")], cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("normal_execution_allowed_lock_invalid", result.stderr)


if __name__ == "__main__":
    unittest.main()
