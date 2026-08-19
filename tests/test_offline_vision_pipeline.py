#!/usr/bin/env python3
"""B5-VISION offline-only photo-to-simulation-target tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "offline_vision_pipeline.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OfflineVisionPipelineTest(unittest.TestCase):
    def make_fixture(self, root: Path, *, size=(160, 120), sparse=False) -> dict[str, Path]:
        width, height = size
        image_array = np.full((height, width, 3), 30, dtype=np.uint8)
        if width >= 64 and height >= 64:
            image_array[10 : height - 10, 20 : width - 20] = [150, 115, 105]
        image = root / "rgb.png"
        Image.fromarray(image_array).save(image)
        depth_array = np.zeros((height, width), dtype=np.uint16)
        if width >= 64 and height >= 64:
            if sparse:
                depth_array[height // 2 - 4 : height // 2 + 4, width // 2 - 4 : width // 2 + 4] = 4000
            else:
                depth_array[10 : height - 10, 20 : width - 20] = 4000
        depth = root / "depth_z16.npy"
        np.save(depth, depth_array)
        meta = root / "meta.json"
        meta.write_text(json.dumps({"depth_scale_m_per_unit": 0.0001, "intrinsics": {"fx": 120.0, "fy": 120.0, "ppx": width / 2, "ppy": height / 2}}), encoding="utf-8")
        candidate = root / "candidate.json"
        candidate.write_text(json.dumps({"schema_version": "b3.camera-extrinsics-candidate.v1", "candidate_id": "fixture-candidate", "candidate_valid": True, "formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "matrix": {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation_m": [0.1, 0.2, 0.3]}}), encoding="utf-8")
        return {"image": image, "depth": depth, "meta": meta, "candidate": candidate}

    def run_pipeline(self, fixture: dict[str, Path], output: Path, *extra: str):
        command = [sys.executable, str(SCRIPT), "--image", str(fixture["image"]), "--depth", str(fixture["depth"]), "--meta", str(fixture["meta"]), "--candidate-extrinsics", str(fixture["candidate"]), "--expected-extrinsics-sha256", sha256(fixture["candidate"]), "--formal-extrinsics", str(output.parent / "missing-camera-to-base.json"), "--out", str(output), *extra]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        return result, json.loads(output.read_text(encoding="utf-8"))

    def test_normal_photo_outputs_acupoints_confidence_hash_and_sim_targets(self):
        with tempfile.TemporaryDirectory(prefix="b5-vision-normal-") as directory:
            root = Path(directory); fixture = self.make_fixture(root); result, report = self.run_pipeline(fixture, root / "result.json")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(report["pipeline_valid"]); self.assertTrue(report["offline_simulation_valid"])
            self.assertEqual(report["acupoint_count"], 7); self.assertEqual(len(report["input"]["image_sha256"]), 64)
            self.assertFalse(report["formal_use_allowed"]); self.assertTrue(report["promotion_locked"]); self.assertFalse(report["execution_allowed"])
            self.assertIn("formal_extrinsics_missing", report["formal_blocking_reasons"])
            self.assertTrue(all(item["coordinate_confidence"] >= 0.55 for item in report["acupoints"]))
            self.assertTrue(all(item["simulation_endpoint_target"]["executable"] is False for item in report["acupoints"]))
            self.assertTrue(all("point_robot_candidate_m" in item for item in report["acupoints"]))
            self.assertEqual(report["hardware_access"], {"d405_accessed": False, "camera_device_opened": False, "nano_accessed": False, "serial_accessed": False, "motor_command_generated": False})

    def test_missing_image_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="b5-vision-image-") as directory:
            root = Path(directory); fixture = self.make_fixture(root); fixture["image"] = root / "absent.png"; result, report = self.run_pipeline(fixture, root / "result.json")
            self.assertEqual(result.returncode, 2); self.assertIn("image_missing", report["blocking_reasons"]); self.assertEqual(report["acupoint_count"], 0)

    def test_invalid_image_dimensions_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="b5-vision-size-") as directory:
            root = Path(directory); fixture = self.make_fixture(root, size=(32, 32)); result, report = self.run_pipeline(fixture, root / "result.json")
            self.assertEqual(result.returncode, 2); self.assertIn("image_dimensions_invalid", report["blocking_reasons"])

    def test_missing_depth_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="b5-vision-depth-") as directory:
            root = Path(directory); fixture = self.make_fixture(root); fixture["depth"] = root / "absent.npy"; result, report = self.run_pipeline(fixture, root / "result.json")
            self.assertEqual(result.returncode, 2); self.assertIn("depth_missing", report["blocking_reasons"])

    def test_missing_candidate_extrinsics_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="b5-vision-extrinsics-") as directory:
            root = Path(directory); fixture = self.make_fixture(root); digest = sha256(fixture["candidate"]); fixture["candidate"].unlink(); output = root / "result.json"
            command = [sys.executable, str(SCRIPT), "--image", str(fixture["image"]), "--depth", str(fixture["depth"]), "--meta", str(fixture["meta"]), "--candidate-extrinsics", str(fixture["candidate"]), "--expected-extrinsics-sha256", digest, "--out", str(output)]
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True); report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 2); self.assertIn("candidate_extrinsics_missing", report["blocking_reasons"]); self.assertEqual(report["acupoints"], [])

    def test_candidate_extrinsics_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="b5-vision-hash-") as directory:
            root = Path(directory); fixture = self.make_fixture(root); output = root / "result.json"
            command = [sys.executable, str(SCRIPT), "--image", str(fixture["image"]), "--depth", str(fixture["depth"]), "--meta", str(fixture["meta"]), "--candidate-extrinsics", str(fixture["candidate"]), "--expected-extrinsics-sha256", "0" * 64, "--out", str(output)]
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True); report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 2); self.assertIn("candidate_extrinsics_hash_mismatch", report["blocking_reasons"])

    def test_low_confidence_blocks_targets(self):
        with tempfile.TemporaryDirectory(prefix="b5-vision-confidence-") as directory:
            root = Path(directory); fixture = self.make_fixture(root); result, report = self.run_pipeline(fixture, root / "result.json", "--min-confidence", "0.99")
            self.assertEqual(result.returncode, 2); self.assertFalse(report["pipeline_valid"]); self.assertTrue(any(reason.startswith("low_confidence:") for reason in report["blocking_reasons"]))
            self.assertFalse(report["execution_allowed"]); self.assertFalse(report["entity_action_authorized"])
            self.assertTrue(all(item["simulation_endpoint_target"] is None for item in report["acupoints"]))

    def test_existing_offline_sample_is_readable_when_present(self):
        sample = ROOT / "data" / "d405_samples" / "back_20260617_212933_470"
        if not all((sample / name).is_file() for name in ("rgb.png", "depth_z16.npy", "meta.json")):
            self.skipTest("checked-in B1 sample not present")
        with tempfile.TemporaryDirectory(prefix="b5-vision-existing-") as directory:
            root = Path(directory); fixture = self.make_fixture(root); fixture.update(image=sample / "rgb.png", depth=sample / "depth_z16.npy", meta=sample / "meta.json")
            result, report = self.run_pipeline(fixture, root / "result.json", "--min-confidence", "0.40")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout); self.assertGreater(report["target_region"]["confidence"], 0.40); self.assertEqual(report["acupoint_count"], 7)

    def test_source_has_no_hardware_or_command_dependencies(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("pyrealsense", "import serial", "/dev/tty", "shared_memory", "send_acupoint", "motor_command_written", "target_command_seq"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
