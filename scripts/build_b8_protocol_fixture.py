#!/usr/bin/env python3
"""Write the checked-in B8 offline protocol fixture with its content hash."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "tasks" / "B8-LOW-SPEED-NONCONTACT-RECORD.example.json"
SCRIPT = Path(__file__).with_name("b8_low_speed_noncontact_prep.py")
SPEC = importlib.util.spec_from_file_location("b8_prep", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def protocol() -> dict:
    value = {
        "schema_version": MODULE.SCHEMA_VERSION,
        "request_id": "b8-protocol-20260824-0001",
        "platform": "x86_64_vm",
        "simulation_only": True,
        "nano_tested": False,
        "arm64_tested": False,
        "entity_experiment": "not_run",
        "hardware_authorized": False,
        "entity_motion_authorized": False,
        "h1_status": "H1_EVIDENCE_INCOMPLETE",
        "b8_safety_gate_status": "PREPARATION_ONLY",
        "software_commit": "9e0c4b925062b0a7c8fd2fa25fd985fe9798402b",
        "nano_commit": MODULE.PLACEHOLDER,
        "entity_device_identity": {
            "nano_host": MODULE.PLACEHOLDER,
            "device_model": MODULE.PLACEHOLDER,
            "serial_path": MODULE.PLACEHOLDER,
            "usb_vid": MODULE.PLACEHOLDER,
            "usb_pid": MODULE.PLACEHOLDER,
            "serial_number": MODULE.PLACEHOLDER,
            "firmware_version": MODULE.PLACEHOLDER,
        },
        "roles": {
            "operator": "PLACEHOLDER_REQUIRES_APPROVAL",
            "emergency_stop_lead": "PLACEHOLDER_REQUIRES_APPROVAL",
            "independent_reviewer": "PLACEHOLDER_REQUIRES_APPROVAL",
        },
        "preconditions": {
            "environment_identity_recorded": True,
            "h1_incomplete_acknowledged": True,
            "no_entity_execution_authorized": True,
            "offline_fixture_only": True,
            "physical_workspace_clear_rule_defined": True,
            "operator_and_estop_roles_required": True,
            "manual_step_confirmation_required": True,
            "post_step_record_required": True,
        },
        "future_entity_parameters": {
            "axis": MODULE.PLACEHOLDER,
            "direction": MODULE.PLACEHOLDER,
            "speed": MODULE.PLACEHOLDER,
            "displacement": MODULE.PLACEHOLDER,
            "stop_distance_limit": MODULE.PLACEHOLDER,
        },
        "single_step_policy": {
            "single_axis_only": True,
            "single_discrete_action_only": True,
            "continuous_jog_forbidden": True,
            "automatic_sequence_forbidden": True,
            "complete_left_route_forbidden": True,
            "complete_right_route_forbidden": True,
            "acupoint_sequence_forbidden": True,
            "human_contact_forbidden": True,
            "dummy_contact_forbidden": True,
            "workspace_clear_required": True,
            "operator_present_required": True,
            "emergency_stop_lead_present_required": True,
            "safety_state_reread_before_each_step": True,
            "manual_confirmation_before_each_step": True,
            "record_after_each_step": True,
            "automatic_recovery_forbidden": True,
            "new_request_id_for_recovery": True,
        },
        "stop_conditions": sorted(MODULE.REQUIRED_STOP_CONDITIONS),
        "recovery_policy": dict(MODULE.REQUIRED_RECOVERY),
        "rollback": {
            "on_no_go": "keep all entity outputs disabled; do not start hardware",
            "on_anomaly": "stop immediately; preserve evidence; do not auto-recover",
            "evidence_location": "docs/progress/evidence/B8-LOW-SPEED-NONCONTACT/",
        },
        "evidence": {
            "raw_log_location": "docs/progress/evidence/B8-LOW-SPEED-NONCONTACT/",
            "raw_log_sha256": MODULE.PLACEHOLDER,
            "recorded_at_utc": MODULE.PLACEHOLDER,
        },
        "experiment_conclusion": "NO_GO_PREPARATION_ONLY",
    }
    value["source_sha256"] = MODULE.digest(value)
    return value


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(protocol(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)
