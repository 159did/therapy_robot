#!/usr/bin/env python3
"""Tests for the offline S3 entity repeatability preflight."""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "s3_endpoint_repeatability_preflight.py"
if not SCRIPT.is_file():
    SCRIPT = Path(__file__).with_name("s3_endpoint_repeatability_preflight.py")
SPEC = importlib.util.spec_from_file_location("s3_preflight", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def valid_snapshot() -> dict:
    fields = {field: False for field in MODULE.REQUIRED_FIELDS}
    fields.update({
        "schema_version": MODULE.SCHEMA_VERSION,
        "platform": "aarch64_nano", "host": "nano-test-host",
        "software_commit": MODULE.S3_COMMIT, "nano_commit": MODULE.S3_COMMIT,
        "h1_status": "H1_ENTITY_READONLY_PASS", "hardware_mode": "HARDWARE_CONTROL",
        "execution_allowed": True, "entity_action_authorized": True,
        "entity_motion_authorized": True, "feedback_valid": True,
        "feedback_age_ms": 5.0, "feedback_max_age_ms": 250.0,
        "watchdog_state": "OK", "limit_state": "CLEAR", "collision_state": "CLEAR",
        "brake_state_known": True, "brake_engaged": True, "estop_available": True,
        "workspace_clear": True, "operator_present": True, "estop_lead_present": True,
        "request_id": "s3-tonight-20260827", "authorization_id": "auth-tonight-20260827",
        "authorization_expiry_utc": "2026-08-27T23:59:00Z", "selected_points": 1,
        "repetitions": 3, "retreat_radius_m": 0.015, "simulation_only": False,
        "nano_tested": True, "arm64_tested": True, "entity_hardware_tested": True,
        "serial_accessed": False, "d405_accessed": False,
        "motor_command_generated": False, "motor_target_generated": False,
        "serial_payload_generated": False, "shared_memory_written": False,
    })
    return fields


class S3PreflightTests(unittest.TestCase):
    def test_complete_snapshot_is_manual_review_only(self):
        report = MODULE.build_report(MODULE.validate_snapshot(valid_snapshot()))
        self.assertEqual(report["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertFalse(report["go"])
        self.assertFalse(report["motion_authorized"])
        self.assertEqual(report["selected_points"], 1)
        self.assertEqual(report["repetitions"], 3)
        self.assertEqual(report["retreat_radius_m"], 0.015)
        for field in ("execution_allowed", "entity_action_authorized", "entity_motion_authorized", "motor_command_generated", "motor_target_generated", "serial_payload_generated", "shared_memory_written", "serial_accessed", "d405_accessed"):
            self.assertFalse(report[field])

    def test_each_safety_failure_is_blocked(self):
        mutations = (
            ("h1_status", "H1_EVIDENCE_INCOMPLETE", "h1_status_not_entity_readonly_pass"),
            ("hardware_mode", "HARDWARE_READONLY", "hardware_mode_not_explicit"),
            ("feedback_valid", False, "feedback_invalid"),
            ("watchdog_state", "TIMEOUT", "watchdog_timeout"),
            ("limit_state", "ABNORMAL", "soft_limit_abnormal"),
            ("collision_state", "ABNORMAL", "collision_abnormal"),
            ("brake_state_known", False, "brake_state_unknown"),
            ("estop_available", False, "emergency_stop_unavailable"),
            ("repetitions", 101, "repetitions_out_of_range"),
            ("retreat_radius_m", 0.01, "retreat_radius_m_must_be_0.015"),
        )
        for field, value, reason in mutations:
            with self.subTest(field=field):
                snapshot = valid_snapshot(); snapshot[field] = value
                with self.assertRaises(MODULE.PreflightError) as error:
                    MODULE.validate_snapshot(snapshot)
                self.assertIn(reason, str(error.exception))

    def test_exact_schema_and_non_finite_values_are_rejected(self):
        snapshot = valid_snapshot(); snapshot["extra"] = True
        with self.assertRaises(MODULE.PreflightError):
            MODULE.validate_snapshot(snapshot)
        snapshot = valid_snapshot(); snapshot["feedback_age_ms"] = math.nan
        with self.assertRaises(MODULE.PreflightError):
            MODULE.validate_snapshot(snapshot)

    def test_cli_no_go_never_emits_motion_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.json"; output = Path(directory) / "report.json"
            snapshot = valid_snapshot(); snapshot["h1_status"] = "H1_EVIDENCE_INCOMPLETE"
            source.write_text(json.dumps(snapshot), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "NO_GO")
            self.assertFalse(report["motion_authorized"])
            self.assertFalse(report["motor_command_generated"])

    def test_source_has_no_device_or_process_access(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("import serial", "import socket", "subprocess", "multiprocessing.shared_memory", "/dev/tty", "run-jetson", "pyrealsense", "write_serial"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
