#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "b6" / "validate_end_effector_command.py"
INPUT_SCHEMA = ROOT / "scripts" / "b6" / "end_effector_command.schema.json"
RESULT_SCHEMA = ROOT / "scripts" / "b6" / "end_effector_validation_result.schema.json"
EXAMPLES = ROOT / "docs" / "tasks" / "B6-EE-CONTRACT.examples"
SPEC = importlib.util.spec_from_file_location("b6_validator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def make_command() -> dict:
    document = {
        "schema_version": "b6.end-effector-command.v1",
        "command_id": "ee-demo-0001",
        "sequence": 1,
        "created_at": "2026-08-20T04:00:00Z",
        "source": "offline_vision",
        "idempotency_key": "ee-demo-0001-v1",
        "coordinate_frame": "robot_base_candidate",
        "position_m": [0.1609, 0.1728, 1.2935],
        "orientation_policy": "keep_current",
        "target_kind": "offline_simulation_only",
        "executable": False,
        "max_speed": {"value": 0.02, "unit": "m/s"},
        "max_acceleration": {"value": 0.10, "unit": "m/s^2"},
        "max_jerk": {"supported": False, "value": None, "unit": "unsupported"},
        "timeout_ms": 120000,
        "approach_offset_m": [0.0, 0.0, 0.05],
        "retract_offset_m": [0.0, 0.0, 0.08],
        "simulation_only": True,
        "formal_use_allowed": False,
        "promotion_locked": True,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "h1_required": True,
        "feedback_required": True,
        "emergency_stop_required_clear": True,
        "collision_check_required": True,
        "status": "APPROACH",
    }
    document["contract_sha256"] = MODULE.contract_hash(document)
    return document


class B6ContractTests(unittest.TestCase):
    def test_normal_candidate_command_validates_and_is_simulation_only(self):
        result = MODULE.validate(make_command())
        self.assertTrue(result["valid"])
        self.assertFalse(result["executable"])
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["nano_deployment_authorized"])
        self.assertTrue(result["promotion_locked"])
        self.assertFalse(result["motor_target_generated"])
        self.assertFalse(result["serial_payload_generated"])
        Draft202012Validator(json.loads(RESULT_SCHEMA.read_text())).validate(result)

    def test_missing_field_blocks(self):
        value = make_command(); del value["approach_offset_m"]
        with self.assertRaisesRegex(MODULE.ContractError, "missing_fields:approach_offset_m"):
            MODULE.validate(value)

    def test_unknown_field_blocks(self):
        value = make_command(); value["future_field"] = 1
        with self.assertRaisesRegex(MODULE.ContractError, "unknown_fields:future_field"):
            MODULE.validate(value)

    def test_unit_error_blocks(self):
        value = make_command(); value["max_speed"]["unit"] = "mm/s"; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "max_speed_unit_invalid"):
            MODULE.validate(value)

    def test_coordinate_frame_error_blocks(self):
        value = make_command(); value["coordinate_frame"] = "camera"; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "coordinate_frame_invalid"):
            MODULE.validate(value)

    def test_workspace_bounds_block(self):
        value = make_command(); value["position_m"][2] = 2.0; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "position_z_outside_workspace"):
            MODULE.validate(value)

    def test_permission_unlock_blocks(self):
        value = make_command(); value["execution_allowed"] = True; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "execution_allowed_must_be_false"):
            MODULE.validate(value)

    def test_candidate_coordinate_cannot_be_executable(self):
        value = make_command(); value["executable"] = True; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "candidate_coordinate_cannot_be_executable"):
            MODULE.validate(value)

    def test_promotion_unlock_blocks(self):
        value = make_command(); value["promotion_locked"] = False; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "promotion_locked_must_be_true"):
            MODULE.validate(value)

    def test_emergency_stop_not_clear_blocks(self):
        value = make_command(); value["emergency_stop_required_clear"] = False; value["status"] = "STOPPED"; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "emergency_stop_required_clear_must_be_true"):
            MODULE.validate(value)

    def test_hash_mismatch_blocks(self):
        value = make_command(); value["position_m"][0] = 0.2
        with self.assertRaisesRegex(MODULE.ContractError, "contract_sha256_mismatch"):
            MODULE.validate(value)

    def test_created_at_requires_complete_utc_timestamp(self):
        value = make_command(); value["created_at"] = "2026-08-20Z"; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "created_at_must_be_utc_iso8601"):
            MODULE.validate(value)

    def test_negative_speed_and_zero_offsets_block(self):
        value = make_command(); value["max_speed"]["value"] = -0.1; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "max_speed_must_be_positive"):
            MODULE.validate(value)

    def test_nonfinite_and_experimental_limit_violations_block(self):
        for invalid in (float("nan"), float("inf"), float("-inf")):
            value = make_command(); value["position_m"][0] = invalid
            with self.assertRaisesRegex(MODULE.ContractError, "position_m\\[0\\]_must_be_finite"):
                MODULE.validate(value)
        value = make_command(); value["max_speed"]["value"] = 0.051; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "max_speed_exceeds_experimental_limit"):
            MODULE.validate(value)
        value = make_command(); value["max_acceleration"]["value"] = 0.201; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "max_acceleration_exceeds_experimental_limit"):
            MODULE.validate(value)
        value = make_command(); value["max_jerk"] = {"supported": True, "value": 0.1, "unit": "m/s^3"}; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "max_jerk_must_be_explicitly_unsupported"):
            MODULE.validate(value)
        value = make_command(); value["approach_offset_m"] = [0.0, 0.0, 0.0]; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "approach_offset_m_must_be_non_contact"):
            MODULE.validate(value)

    def test_offset_endpoint_outside_workspace_blocks(self):
        value = make_command(); value["position_m"][2] = 1.75; value["approach_offset_m"] = [0.0, 0.0, 0.10]; value["contract_sha256"] = MODULE.contract_hash(value)
        with self.assertRaisesRegex(MODULE.ContractError, "approach_offset_m_z_endpoint_outside_workspace"):
            MODULE.validate(value)

    def test_cli_writes_fail_closed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "command.json"; output = root / "report.json"
            source.write_text(json.dumps(make_command()), encoding="utf-8")
            result = __import__("subprocess").run(["python3", str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            report = json.loads(output.read_text())
            self.assertTrue(report["valid"])
            Draft202012Validator(json.loads(RESULT_SCHEMA.read_text())).validate(report)

            source.write_text("{}", encoding="utf-8")
            result = __import__("subprocess").run(["python3", str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            report = json.loads(output.read_text())
            self.assertFalse(report["valid"])
            self.assertFalse(report["motor_target_generated"])
            self.assertFalse(report["serial_payload_generated"])
            self.assertFalse(report["nano_deployment_authorized"])
            Draft202012Validator(json.loads(RESULT_SCHEMA.read_text())).validate(report)

            source.write_text('{"sequence":1,"sequence":2}', encoding="utf-8")
            result = __import__("subprocess").run(["python3", str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(output.read_text())["blocking_reason"], "duplicate_field:sequence")

            source.write_text('{"position_m":[NaN,0,1]}', encoding="utf-8")
            result = __import__("subprocess").run(["python3", str(SCRIPT), str(source), "--out", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(output.read_text())["blocking_reason"], "non_finite_json_constant:NaN")

    def test_json_schemas_are_well_formed_and_valid_command_matches(self):
        input_schema = json.loads(INPUT_SCHEMA.read_text(encoding="utf-8"))
        result_schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(input_schema)
        Draft202012Validator.check_schema(result_schema)
        Draft202012Validator(input_schema).validate(make_command())

    def test_checked_in_examples_have_expected_results(self):
        expected = {
            "valid-command.json": None,
            "missing-field.json": "missing_fields:approach_offset_m",
            "unit-error.json": "max_speed_unit_invalid",
            "coordinate-frame-error.json": "coordinate_frame_invalid",
            "workspace-out-of-bounds.json": "position_z_outside_workspace",
            "permission-unlock.json": "execution_allowed_must_be_false",
            "emergency-stop.json": "emergency_stop_required_clear_must_be_true",
            "hash-mismatch.json": "contract_sha256_mismatch",
        }
        for name, error in expected.items():
            value = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
            if error is None:
                self.assertTrue(MODULE.validate(value)["valid"], name)
            else:
                with self.assertRaisesRegex(MODULE.ContractError, error, msg=name):
                    MODULE.validate(value)

    def test_source_has_no_hardware_or_motor_output_dependencies(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("pyrealsense", "import serial", "import socket", "shared_memory", "subprocess.Popen", "target_native", "motor_axis", "/dev/tty", "write_serial"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
