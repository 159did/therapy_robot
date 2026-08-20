#!/usr/bin/env python3
"""Build deterministic B6 contract examples; this performs no hardware access."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = Path(__file__).with_name("validate_end_effector_command.py")
EXAMPLE_DIR = ROOT / "docs" / "tasks" / "B6-EE-CONTRACT.examples"
SPEC = importlib.util.spec_from_file_location("b6_validator", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(VALIDATOR)


def command() -> dict:
    value = {
        "schema_version": "b6.end-effector-command.v1",
        "command_id": "ee-demo-dazhui-0001",
        "sequence": 1,
        "created_at": "2026-08-20T04:00:00Z",
        "source": "offline_vision",
        "idempotency_key": "ee-demo-dazhui-0001-v1",
        "coordinate_frame": "robot_base_candidate",
        "position_m": [0.1609163181992805, 0.1728330895391088, 1.2935009362530452],
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
    value["contract_sha256"] = VALIDATOR.contract_hash(value)
    return value


def signed(mutator) -> dict:
    value = copy.deepcopy(command())
    mutator(value)
    value["contract_sha256"] = VALIDATOR.contract_hash(value)
    return value


def main() -> int:
    examples = {
        "valid-command.json": command(),
        "missing-field.json": signed(lambda value: value.pop("approach_offset_m")),
        "unit-error.json": signed(lambda value: value["max_speed"].__setitem__("unit", "mm/s")),
        "coordinate-frame-error.json": signed(lambda value: value.__setitem__("coordinate_frame", "d405_camera")),
        "workspace-out-of-bounds.json": signed(lambda value: value.__setitem__("position_m", [0.1609, 0.1728, 2.0])),
        "permission-unlock.json": signed(lambda value: value.__setitem__("execution_allowed", True)),
        "emergency-stop.json": signed(
            lambda value: value.update({"status": "STOPPED", "emergency_stop_required_clear": False})
        ),
        "hash-mismatch.json": command(),
    }
    examples["hash-mismatch.json"]["contract_sha256"] = "0" * 64
    EXAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    for name, value in examples.items():
        (EXAMPLE_DIR / name).write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"wrote {len(examples)} examples to {EXAMPLE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
