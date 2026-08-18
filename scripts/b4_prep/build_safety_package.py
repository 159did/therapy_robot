#!/usr/bin/env python3
"""Build a deterministic V2-F/T1 software safety package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PACKAGE_SCHEMA = "b4.prep.d.v1"
GATE_SCHEMA = "b4.prep.d.v2f-promotion-gate.v1"
T1_SCHEMA = "b4.prep.d.t1-plan-report.v1"
RISK_SCHEMA = "b4.prep.d.risk-register.v1"
CHECKLIST_SCHEMA = "b4.prep.d.operator-checklist.v1"
TEMPLATE_SCHEMA = "b4.prep.d.report-template.v1"
FIXED_FALSE = ("execution_allowed", "entity_action_authorized", "nano_deployment_authorized", "formal_use_allowed", "human_contact_allowed", "entity_camera_accessed")


class PackageError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise PackageError(f"file_read_failed:{exc}") from exc


def load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"{label}_json_invalid:{exc}") from exc
    if not isinstance(value, dict):
        raise PackageError(f"{label}_not_object")
    return value


def fixed_false(value: dict[str, Any], label: str) -> None:
    for key in FIXED_FALSE:
        if value.get(key) is not False:
            raise PackageError(f"{label}_{key}_must_be_false")


def validate_gate(value: dict[str, Any]) -> None:
    if value.get("schema_version") != GATE_SCHEMA:
        raise PackageError("promotion_gate_schema_invalid")
    fixed_false(value, "promotion_gate")
    if value.get("promotion_locked") is not True:
        raise PackageError("promotion_gate_lock_invalid")
    if not isinstance(value.get("candidate_summary"), dict) or not isinstance(value.get("promotion_gate"), dict):
        raise PackageError("promotion_gate_summary_missing")


def validate_t1(value: dict[str, Any]) -> None:
    if value.get("schema_version") != T1_SCHEMA:
        raise PackageError("t1_report_schema_invalid")
    fixed_false(value, "t1_report")
    if value.get("promotion_locked") is not True or value.get("synthetic") is not True:
        raise PackageError("t1_report_lock_invalid")
    if value.get("phase_order") != ["NON_CONTACT_APPROACH", "HOLD", "RETRACT"]:
        raise PackageError("t1_report_phase_order_invalid")


def validate_risk(value: dict[str, Any]) -> None:
    if value.get("schema_version") != RISK_SCHEMA:
        raise PackageError("risk_schema_invalid")
    risks = value.get("risks")
    if not isinstance(risks, list) or not risks:
        raise PackageError("risk_entries_missing")
    ids: list[str] = []
    for risk in risks:
        if not isinstance(risk, dict) or not all(isinstance(risk.get(key), str) and risk[key] for key in ("id", "hazard", "trigger", "mitigation", "residual_risk")):
            raise PackageError("risk_entry_invalid")
        ids.append(risk["id"])
        if risk.get("blocking") is not True:
            raise PackageError("risk_must_remain_blocking")
    if ids != sorted(set(ids)):
        raise PackageError("risk_ids_not_normalized")


def validate_checklist(value: dict[str, Any]) -> None:
    if value.get("schema_version") != CHECKLIST_SCHEMA:
        raise PackageError("checklist_schema_invalid")
    for section in ("preflight", "in_progress", "postflight"):
        items = value.get(section)
        if not isinstance(items, list) or not items or any(not isinstance(item, str) or not item for item in items):
            raise PackageError(f"checklist_{section}_invalid")
    if value.get("operator_confirmed") is not False:
        raise PackageError("operator_confirmation_must_be_false")


def validate_template(value: dict[str, Any]) -> None:
    if value.get("schema_version") != TEMPLATE_SCHEMA:
        raise PackageError("template_schema_invalid")
    required = {"package_id", "promotion_gate", "t1_plan", "events", "evidence_hashes", "blocking_reasons", "entity_access_declaration"}
    fields = value.get("required_fields")
    if not isinstance(fields, list) or set(fields) != required:
        raise PackageError("template_required_fields_invalid")


def build_package(gate: dict[str, Any], t1: dict[str, Any], risk: dict[str, Any], checklist: dict[str, Any], template: dict[str, Any], hashes: dict[str, str]) -> dict[str, Any]:
    core = {
        "schema_version": PACKAGE_SCHEMA,
        "valid": True,
        "formal_use_allowed": False,
        "promotion_locked": True,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "human_contact_allowed": False,
        "entity_camera_accessed": False,
        "promotion_gate": {"report_schema": gate["schema_version"], "report_valid": gate["valid"], "report_hash": hashes["promotion_gate"], "blocking_reasons": gate["promotion_gate"].get("blocking_reasons", [])},
        "t1_plan": {"report_schema": t1["schema_version"], "report_valid": t1["valid"], "report_hash": hashes["t1_plan"], "phase_order": t1["phase_order"]},
        "risk_register": {"schema_version": risk["schema_version"], "risk_ids": [item["id"] for item in risk["risks"]], "blocking": True, "input_hash": hashes["risk_register"]},
        "operator_checklist": {"schema_version": checklist["schema_version"], "sections": ["preflight", "in_progress", "postflight"], "operator_confirmed": False, "input_hash": hashes["operator_checklist"]},
        "report_template": {"schema_version": template["schema_version"], "required_fields": template["required_fields"], "input_hash": hashes["report_template"]},
        "evidence_hashes": [{"name": key, "sha256": hashes[key]} for key in sorted(hashes)],
        "blocking_reasons": ["formal_camera_promotion_requires_independent_authorization", "human_contact_not_allowed_in_b4_prep", "entity_access_not_performed"],
        "entity_access_declaration": {"nano_deployed": False, "serial_accessed": False, "d405_accessed": False, "motors_enabled": False, "motors_zeroed": False, "motors_moved": False, "human_contact": False},
        "rollback": {"owner": "independent_safety_owner", "triggers": ["unknown_state", "hash_mismatch", "operator_abort", "estop", "watchdog_timeout"], "actions": ["stop_prepared_workflow", "preserve_evidence", "return_to_prepared_state", "record_blocking_reason"]},
    }
    report_hash = hashlib.sha256(canonical(core)).hexdigest()
    return {**core, "package_id": "b4-d-package-" + report_hash[:16], "package_hash": report_hash}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("promotion-gate", "t1-plan", "risk-register", "operator-checklist", "report-template"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv or sys.argv[1:])
    paths = {"promotion_gate": args.promotion_gate, "t1_plan": args.t1_plan, "risk_register": args.risk_register, "operator_checklist": args.operator_checklist, "report_template": args.report_template}
    values: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    errors: list[str] = []
    try:
        for key, path in paths.items():
            values[key] = load(path, key)
            hashes[key] = file_hash(path)
        validate_gate(values["promotion_gate"])
        validate_t1(values["t1_plan"])
        validate_risk(values["risk_register"])
        validate_checklist(values["operator_checklist"])
        validate_template(values["report_template"])
    except PackageError as exc:
        errors.append(str(exc))
    if errors:
        package = {
            "schema_version": PACKAGE_SCHEMA, "valid": False,
            "formal_use_allowed": False, "promotion_locked": True,
            "execution_allowed": False, "entity_action_authorized": False,
            "nano_deployment_authorized": False, "human_contact_allowed": False,
            "entity_camera_accessed": False, "package_id": None,
            "package_hash": None, "blocking_reasons": sorted(set(errors)),
        }
    else:
        package = build_package(values["promotion_gate"], values["t1_plan"], values["risk_register"], values["operator_checklist"], values["report_template"], hashes)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"output_write_failed:{exc}", file=sys.stderr)
        return 2
    if errors:
        print("invalid B4-PREP-D package: " + "; ".join(sorted(set(errors))), file=sys.stderr)
        return 1
    print(package["package_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
