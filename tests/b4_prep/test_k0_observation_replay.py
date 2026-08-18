#!/usr/bin/env python3

from __future__ import annotations

import copy
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
TOOL_PATH = PROJECT_ROOT / "scripts" / "b4_prep" / "k0_observation_replay.py"
FIXTURE_DIR = HERE / "fixtures" / "k0_observation"
SPEC = importlib.util.spec_from_file_location("k0_observation_replay", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sign(document: dict) -> dict:
    result = copy.deepcopy(document)
    result["integrity"] = {"algorithm": "sha256", "payload_sha256": MODULE.payload_digest(result)}
    return result


def nominal() -> dict:
    return sign(
        {
            "schema_version": "b4.k0-observation.v1",
            "synthetic": True,
            "source": {
                "kind": "synthetic_fixture",
                "session_id": "synthetic-stop-positive",
                "device_id": "none",
                "generated_at_utc": "2026-08-18T02:30:00Z",
            },
            "safety": {
                "formal_use_allowed": False,
                "execution_allowed": False,
                "entity_action_authorized": False,
                "nano_deployment_authorized": False,
                "h1_window_authorized": False,
            },
            "limits": {
                "height_unit": "normalized",
                "velocity_unit": "normalized_per_second",
                "time_unit": "milliseconds",
                "lower": 0.1,
                "upper": 0.9,
                "max_feedback_age_ms": 50,
                "max_sample_gap_ms": 100,
            },
            "samples": [
                {"sequence": 1, "monotonic_ms": 1000, "height": 0.4, "velocity": 0.02, "brake_state": "released", "feedback_quality": "valid", "feedback_age_ms": 5, "stop_state": "observing"},
                {"sequence": 2, "monotonic_ms": 1050, "height": 0.401, "velocity": 0.02, "brake_state": "released", "feedback_quality": "valid", "feedback_age_ms": 5, "stop_state": "stop_requested"},
                {"sequence": 3, "monotonic_ms": 1100, "height": 0.4017, "velocity": 0.01, "brake_state": "released", "feedback_quality": "valid", "feedback_age_ms": 5, "stop_state": "stopping"},
                {"sequence": 4, "monotonic_ms": 1150, "height": 0.402, "velocity": 0.0, "brake_state": "engaged", "feedback_quality": "valid", "feedback_age_ms": 5, "stop_state": "stopped"},
            ],
        }
    )


class ReplayTests(unittest.TestCase):
    def assert_blocked(self, document: dict, expected: str) -> None:
        with self.assertRaisesRegex(MODULE.ObservationError, expected):
            MODULE.validate_and_replay(document)

    def mutate_and_sign(self, callback) -> dict:
        document = nominal()
        callback(document)
        return sign(document)

    def test_nominal_report_is_deterministic_and_locked(self) -> None:
        document = nominal()
        first = MODULE.validate_and_replay(document)
        second = MODULE.validate_and_replay(document)
        self.assertEqual(first, second)
        self.assertEqual(first["decision"], "offline_observation_accepted")
        self.assertTrue(first["blocking"])
        self.assertAlmostEqual(first["metrics"]["stopping_distance"], 0.001)
        self.assertEqual(first["metrics"]["stopping_duration"], 100)
        self.assertTrue(all(value is False for value in first["safety"].values()))

    def test_missing_and_unknown_fields_are_blocked(self) -> None:
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][0].pop("height")), "missing=height")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][0].update({"command": "move"})), "unknown=command")

    def test_integrity_detects_tampering(self) -> None:
        document = nominal()
        document["samples"][2]["height"] = 0.5
        self.assert_blocked(document, "payload mismatch")

    def test_sequence_and_clock_fail_closed(self) -> None:
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][1].update({"sequence": 1})), "expected 2")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][2].update({"monotonic_ms": 1049})), "clock did not advance")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][2].update({"monotonic_ms": 1200})), "sample gap exceeds limit")

    def test_feedback_and_brake_inconsistency_fail_closed(self) -> None:
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][1].update({"feedback_quality": "lost"})), "feedback is not current")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][1].update({"feedback_age_ms": 51})), "feedback is not current")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][1].update({"brake_state": "engaged"})), "engaged brake conflicts")

    def test_limits_and_nonfinite_values_fail_closed(self) -> None:
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][2].update({"height": 0.95})), "outside declared soft limits")
        nonfinite = nominal()
        nonfinite["samples"][2]["height"] = math.nan
        nonfinite["integrity"]["payload_sha256"] = "0" * 64
        self.assert_blocked(nonfinite, "finite|payload mismatch")

    def test_stop_segment_rules_fail_closed(self) -> None:
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][2].update({"stop_state": "observing"})), "observing after stop request")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][3].update({"stop_state": "stopping", "brake_state": "released", "velocity": 0.005})), "complete stop_requested")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][3].update({"height": 0.4005})), "displacement reversed")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][2].update({"velocity": 0.03})), "speed increased")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["samples"][2].update({"velocity": -0.01})), "velocity reversed")

    def test_positive_and_negative_stops_preserve_distance(self) -> None:
        for direction in (-1.0, 1.0):
            for distance in (0.0001, 0.001, 0.01):
                document = nominal()
                request_height = 0.5
                document["samples"][0].update({"height": request_height - direction * 0.001, "velocity": direction * 0.02})
                document["samples"][1].update({"height": request_height, "velocity": direction * 0.02})
                document["samples"][2].update({"height": request_height + direction * distance * 0.7, "velocity": direction * 0.01})
                document["samples"][3].update({"height": request_height + direction * distance})
                report = MODULE.validate_and_replay(sign(document))
                self.assertAlmostEqual(report["metrics"]["stopping_distance"], distance)

    def test_any_permission_or_real_source_is_blocked(self) -> None:
        self.assert_blocked(self.mutate_and_sign(lambda d: d["safety"].update({"h1_window_authorized": True})), "must remain false")
        self.assert_blocked(self.mutate_and_sign(lambda d: d["source"].update({"device_id": "real-device-id"})), "must be 'none'")
        self.assert_blocked(self.mutate_and_sign(lambda d: d.update({"synthetic": False})), "only synthetic")

    def test_checked_in_fixtures_have_expected_outcomes(self) -> None:
        expected = {
            "nominal.json": True,
            "feedback-lost.json": False,
            "inconsistent-brake.json": False,
            "out-of-order.json": False,
            "tampered.json": False,
            "timeout.json": False,
        }
        self.assertEqual({path.name for path in FIXTURE_DIR.glob("*.json")}, set(expected))
        for name, valid in expected.items():
            document = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
            if valid:
                self.assertTrue(MODULE.validate_and_replay(document)["valid"])
            else:
                with self.assertRaises(MODULE.ObservationError, msg=name):
                    MODULE.validate_and_replay(document)

    def test_cli_returns_nonzero_and_locked_report_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(self.mutate_and_sign(lambda d: d["samples"][1].update({"feedback_quality": "lost"}))), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(TOOL_PATH), str(path)], check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2)
        report = json.loads(completed.stdout)
        self.assertEqual(report["decision"], "blocked")
        self.assertIsNone(report["metrics"])
        self.assertTrue(all(value is False for value in report["safety"].values()))

    def test_cli_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
            completed = subprocess.run([sys.executable, str(TOOL_PATH), str(path)], check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("duplicate key", json.loads(completed.stdout)["errors"][0])

    def test_digest_mode_keeps_real_sources_and_permissions_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "real.json"
            path.write_text(json.dumps(self.mutate_and_sign(lambda d: d["source"].update({"device_id": "real-device-id"}))), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(TOOL_PATH), str(path), "--digest"], check=False, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 2)

    def test_schema_document_is_valid_json(self) -> None:
        schema_path = PROJECT_ROOT / "scripts" / "b4_prep" / "k0_observation.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
