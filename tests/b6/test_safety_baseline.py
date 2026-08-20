#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import ast
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("b6_safety_baseline", ROOT / "scripts" / "b6" / "safety_baseline.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


ENTITY_REQUEST = {"action": MODULE.ACTION_ENTITY_CONTROL, "units": MODULE.NORMALIZED_UNITS}
SIM_REQUEST = {"action": MODULE.ACTION_OFFLINE_SIMULATION, "units": MODULE.NORMALIZED_UNITS}


def hardware_ready(**changes):
    values = {
        "execution_allowed": True,
        "entity_action_authorized": True,
        "hardware_mode": MODULE.HARDWARE_CONTROL,
        "emergency_stop": False,
        "feedback_valid": True,
        "feedback_age_ms": 0.0,
        "limit_state": "CLEAR",
        "collision_state": "CLEAR",
        "watchdog_state": "OK",
        "h1_status": "PASS",
    }
    values.update(changes)
    return MODULE.SafetyState(**values)


class SafetyBaselineTests(unittest.TestCase):
    def test_default_mode_rejects_entity_control(self):
        result = MODULE.evaluate_control_request(MODULE.SafetyState.default(), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("hardware_control_mode_not_explicit", result.reasons)

    def test_h1_not_pass_rejects_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(h1_status="NOT_READY"), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("h1_status_not_pass", result.reasons)

    def test_hardware_readonly_rejects_entity_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(hardware_mode=MODULE.HARDWARE_READONLY), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("hardware_control_mode_not_explicit", result.reasons)

    def test_emergency_stop_rejects_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(emergency_stop=True), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("emergency_stop_active", result.reasons)

    def test_feedback_loss_rejects_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(feedback_valid=False), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("feedback_invalid", result.reasons)

    def test_feedback_expiry_rejects_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(feedback_age_ms=MODULE.MAX_FEEDBACK_AGE_MS + 1), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("feedback_expired", result.reasons)

    def test_watchdog_timeout_rejects_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(watchdog_state="TIMEOUT"), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("watchdog_timeout", result.reasons)

    def test_soft_limit_abnormal_rejects_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(limit_state="ABNORMAL"), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("limit_state_abnormal", result.reasons)

    def test_collision_abnormal_rejects_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(collision_state="ABNORMAL"), ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("collision_state_abnormal", result.reasons)

    def test_false_permission_fields_reject_control(self):
        entity = MODULE.evaluate_control_request(hardware_ready(entity_action_authorized=False), ENTITY_REQUEST)
        execution = MODULE.evaluate_control_request(hardware_ready(execution_allowed=False), ENTITY_REQUEST)
        self.assertFalse(entity.allowed)
        self.assertFalse(execution.allowed)
        self.assertIn("entity_action_not_authorized", entity.reasons)
        self.assertIn("execution_not_allowed", execution.reasons)

    def test_permission_unlock_alone_does_not_authorize_control(self):
        state = MODULE.SafetyState(
            execution_allowed=True,
            entity_action_authorized=True,
        )
        result = MODULE.evaluate_control_request(state, ENTITY_REQUEST)
        self.assertFalse(result.allowed)
        self.assertIn("hardware_control_mode_not_explicit", result.reasons)
        self.assertIn("h1_status_not_pass", result.reasons)

    def test_normal_simulation_allows_offline_simulation(self):
        result = MODULE.evaluate_control_request(MODULE.SafetyState.default(), SIM_REQUEST)
        self.assertTrue(result.allowed)
        self.assertEqual(result.reasons, ("offline_simulation_allowed",))
        self.assertFalse(result.execution_allowed)

    def test_invalid_inputs_fail_closed(self):
        for request in (
            {"action": MODULE.ACTION_ENTITY_CONTROL, "units": float("nan")},
            {"action": MODULE.ACTION_ENTITY_CONTROL, "units": float("inf")},
            {"action": MODULE.ACTION_ENTITY_CONTROL, "units": "degrees"},
            {"action": MODULE.ACTION_ENTITY_CONTROL, "units": MODULE.NORMALIZED_UNITS, "unknown": 1},
            {"action": [], "units": MODULE.NORMALIZED_UNITS},
        ):
            result = MODULE.evaluate_control_request(hardware_ready(), request)
            self.assertFalse(result.allowed)
        self.assertIn("input_non_finite", MODULE.evaluate_control_request(hardware_ready(), {"action": MODULE.ACTION_ENTITY_CONTROL, "units": math.nan}).reasons)
        self.assertIn("units_not_supported", MODULE.evaluate_control_request(hardware_ready(), {"action": MODULE.ACTION_ENTITY_CONTROL, "units": "degrees"}).reasons)
        self.assertIn("unknown_input_field:unknown", MODULE.evaluate_control_request(hardware_ready(), {"action": MODULE.ACTION_ENTITY_CONTROL, "units": MODULE.NORMALIZED_UNITS, "unknown": 1}).reasons)

    def test_source_has_no_hardware_or_transport_dependencies(self):
        source = ROOT / "scripts" / "b6" / "safety_baseline.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Call):
                calls.add(ast.unparse(node.func))
        forbidden_imports = {"serial", "pyrealsense2", "socket", "subprocess", "multiprocessing.shared_memory"}
        forbidden_calls = {"open", "os.open", "subprocess.run", "subprocess.Popen"}
        self.assertTrue(imports.isdisjoint(forbidden_imports))
        self.assertTrue(calls.isdisjoint(forbidden_calls))

    def test_all_gates_pass_only_for_explicit_hardware_control(self):
        result = MODULE.evaluate_control_request(hardware_ready(), ENTITY_REQUEST)
        self.assertTrue(result.allowed)
        self.assertTrue(result.execution_allowed)

    def test_state_mapping_rejects_unknown_fields(self):
        state = MODULE.SafetyState.default().as_dict()
        state["future_unknown"] = True
        with self.assertRaisesRegex(ValueError, "unknown_safety_state_field"):
            MODULE.SafetyState.from_mapping(state)


if __name__ == "__main__":
    unittest.main()
