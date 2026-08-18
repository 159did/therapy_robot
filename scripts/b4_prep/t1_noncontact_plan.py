#!/usr/bin/env python3
"""Validate an offline, non-contact T1 approach/hold/retract plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


PLAN_SCHEMA = "b4.prep.d.t1-plan.v1"
REPORT_SCHEMA = "b4.prep.d.t1-plan-report.v1"
PHASES = ("NON_CONTACT_APPROACH", "HOLD", "RETRACT")
FIXED_FALSE = ("motor_command_written", "execution_allowed", "entity_action_authorized", "nano_deployment_authorized", "human_contact_allowed", "entity_camera_accessed")
FORBIDDEN_KEY_PARTS = ("motor_target", "joint_target", "serial", "shared_memory", "command_target", "entity_offset")


class PlanError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"plan_json_invalid:{exc}") from exc
    if not isinstance(value, dict):
        raise PlanError("plan_not_object")
    return value


def finite_number(value: Any, reason: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PlanError(reason)
    return float(value)


def scan_forbidden(value: Any, path: str = "plan") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in FORBIDDEN_KEY_PARTS):
                raise PlanError(f"forbidden_field:{path}.{key}")
            scan_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_forbidden(child, f"{path}[{index}]")


def validate(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        if plan.get("schema_version") != PLAN_SCHEMA:
            raise PlanError("schema_invalid")
        if not isinstance(plan.get("plan_id"), str) or not plan["plan_id"]:
            raise PlanError("plan_id_missing")
        if plan.get("synthetic") is not True:
            raise PlanError("synthetic_must_be_true")
        for key in FIXED_FALSE:
            if plan.get(key) is not False:
                raise PlanError(f"{key}_must_be_false")
        watchdog = plan.get("watchdog_timeout_ms")
        if not isinstance(watchdog, int) or isinstance(watchdog, bool) or watchdog <= 0 or watchdog > 300_000:
            raise PlanError("watchdog_timeout_invalid")
        phases = plan.get("phases")
        if not isinstance(phases, list) or len(phases) != len(PHASES):
            raise PlanError("phases_must_have_three_items")
        for index, (phase, expected) in enumerate(zip(phases, PHASES)):
            if not isinstance(phase, dict) or phase.get("phase") != expected:
                raise PlanError("phase_order_invalid")
            if phase.get("synthetic") is not True:
                raise PlanError(f"phase_{expected}_synthetic_invalid")
            distance = finite_number(phase.get("distance_normalized"), f"phase_{expected}_distance_invalid")
            speed = finite_number(phase.get("speed_normalized_per_second"), f"phase_{expected}_speed_invalid")
            if distance < 0 or speed < 0 or (expected != "HOLD" and speed <= 0):
                raise PlanError(f"phase_{expected}_motion_values_invalid")
            dwell = phase.get("dwell_ms")
            if not isinstance(dwell, int) or isinstance(dwell, bool) or dwell < 0:
                raise PlanError(f"phase_{expected}_dwell_invalid")
            stops = phase.get("stop_conditions")
            if not isinstance(stops, list) or not stops or any(not isinstance(item, str) or not item for item in stops):
                raise PlanError(f"phase_{expected}_stop_conditions_missing")
            if not isinstance(phase.get("operator_confirmation_required"), bool):
                raise PlanError(f"phase_{expected}_operator_confirmation_invalid")
        safety = plan.get("safety")
        if not isinstance(safety, dict) or safety.get("fail_closed") is not True or safety.get("estop_required") is not True or safety.get("watchdog_required") is not True:
            raise PlanError("safety_policy_invalid")
        rollback = plan.get("rollback")
        if not isinstance(rollback, dict) or not isinstance(rollback.get("trigger_conditions"), list) or not rollback["trigger_conditions"] or not isinstance(rollback.get("actions"), list) or not rollback["actions"]:
            raise PlanError("rollback_plan_invalid")
        scan_forbidden(plan)
    except PlanError as exc:
        errors.append(str(exc))
    return sorted(set(errors))


def build_report(plan: dict[str, Any], errors: list[str], plan_hash: str) -> dict[str, Any]:
    core = {
        "schema_version": REPORT_SCHEMA,
        "valid": not errors,
        "plan_hash": plan_hash,
        "plan_id": plan.get("plan_id"),
        "phase_order": [item.get("phase") for item in plan.get("phases", []) if isinstance(item, dict)],
        "synthetic": True,
        "promotion_locked": True,
        "formal_use_allowed": False,
        "motor_command_written": False,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "human_contact_allowed": False,
        "entity_camera_accessed": False,
        "blocking_reasons": errors,
        "stop_policy": {
            "fail_closed": plan.get("safety", {}).get("fail_closed") if isinstance(plan.get("safety"), dict) else None,
            "estop_required": plan.get("safety", {}).get("estop_required") if isinstance(plan.get("safety"), dict) else None,
            "watchdog_required": plan.get("safety", {}).get("watchdog_required") if isinstance(plan.get("safety"), dict) else None,
        },
    }
    report_hash = digest(core)
    return {**core, "report_id": "b4-d-t1-" + report_hash[:16], "report_hash": report_hash}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv or sys.argv[1:])
    try:
        plan = load(args.plan)
        plan_hash = hashlib.sha256(args.plan.read_bytes()).hexdigest()
        errors = validate(plan)
    except (PlanError, OSError) as exc:
        plan = {}
        plan_hash = ""
        errors = [str(exc)]
    report = build_report(plan, errors, plan_hash)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"output_write_failed:{exc}", file=sys.stderr)
        return 2
    if errors:
        print("invalid T1 plan: " + "; ".join(errors), file=sys.stderr)
        return 1
    print(report["report_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
