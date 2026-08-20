#!/usr/bin/env python3
"""Minimal, centralized, fail-closed safety baseline for future control entry points.

This module is deliberately offline-only.  It validates a safety snapshot and a
typed *intent*; it never opens a device, writes a command, starts a process, or
changes a motor state.  ``offline_simulation`` is the only action allowed in
the default SIMULATION mode.  Physical control requires every gate to pass.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping


SIMULATION = "SIMULATION"
HARDWARE_READONLY = "HARDWARE_READONLY"
HARDWARE_CONTROL = "HARDWARE_CONTROL"
RUN_MODES = frozenset({SIMULATION, HARDWARE_READONLY, HARDWARE_CONTROL})

ACTION_OFFLINE_SIMULATION = "offline_simulation"
ACTION_ENTITY_CONTROL = "entity_control"
ACTION_KINDS = frozenset({ACTION_OFFLINE_SIMULATION, ACTION_ENTITY_CONTROL})
NORMALIZED_UNITS = "normalized"
MAX_FEEDBACK_AGE_MS = 250.0

REQUIRED_STATE_FIELDS = (
    "execution_allowed",
    "entity_action_authorized",
    "hardware_mode",
    "emergency_stop",
    "feedback_valid",
    "feedback_age_ms",
    "limit_state",
    "collision_state",
    "watchdog_state",
    "h1_status",
)
_STATE_FIELD_SET = frozenset(REQUIRED_STATE_FIELDS)
_REQUEST_FIELDS = frozenset({"action", "units"})


@dataclass(frozen=True)
class SafetyState:
    """Central safety snapshot consumed by a future control entry point."""

    execution_allowed: bool = False
    entity_action_authorized: bool = False
    hardware_mode: str = SIMULATION
    emergency_stop: bool = False
    feedback_valid: bool = True
    feedback_age_ms: float = 0.0
    limit_state: str = "CLEAR"
    collision_state: str = "CLEAR"
    watchdog_state: str = "OK"
    h1_status: str = "NOT_READY"

    @classmethod
    def default(cls) -> "SafetyState":
        """Return the locked, offline-safe default state."""

        return cls()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SafetyState":
        """Build a state only when its schema is exact and type-safe."""

        if not isinstance(value, Mapping):
            raise ValueError("safety_state_not_mapping")
        keys = set(value)
        unknown = sorted((key for key in keys if key not in _STATE_FIELD_SET), key=repr)
        missing = sorted(_STATE_FIELD_SET - keys)
        if unknown:
            raise ValueError(f"unknown_safety_state_field:{unknown[0]}")
        if missing:
            raise ValueError(f"missing_safety_state_field:{missing[0]}")
        state = cls(**dict(value))
        errors = validate_safety_state(state)
        if errors:
            raise ValueError(errors[0])
        return state

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SafetyDecision:
    """Pure result of the centralized safety gate."""

    allowed: bool
    reasons: tuple[str, ...]
    action: str
    execution_allowed: bool
    hardware_mode: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "action": self.action,
            "execution_allowed": self.execution_allowed,
            "hardware_mode": self.hardware_mode,
        }


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_safety_state(state: SafetyState) -> list[str]:
    """Return deterministic schema errors for a safety snapshot."""

    errors: list[str] = []
    if not isinstance(state, SafetyState):
        return ["safety_state_type_invalid"]
    for field in ("execution_allowed", "entity_action_authorized", "emergency_stop", "feedback_valid"):
        if not isinstance(getattr(state, field), bool):
            errors.append(f"{field}_must_be_boolean")
    if not isinstance(state.hardware_mode, str) or state.hardware_mode not in RUN_MODES:
        errors.append("hardware_mode_invalid")
    if not _finite_number(state.feedback_age_ms) or float(state.feedback_age_ms) < 0:
        errors.append("feedback_age_ms_invalid")
    if not isinstance(state.limit_state, str) or state.limit_state not in {"CLEAR", "ABNORMAL"}:
        errors.append("limit_state_invalid")
    if not isinstance(state.collision_state, str) or state.collision_state not in {"CLEAR", "ABNORMAL"}:
        errors.append("collision_state_invalid")
    if not isinstance(state.watchdog_state, str) or state.watchdog_state not in {"OK", "TIMEOUT"}:
        errors.append("watchdog_state_invalid")
    if not isinstance(state.h1_status, str) or not state.h1_status:
        errors.append("h1_status_invalid")
    return errors


def _contains_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_contains_non_finite(key) or _contains_non_finite(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite(item) for item in value)
    return False


def _validate_request(request: Mapping[str, Any]) -> list[str]:
    if not isinstance(request, Mapping):
        return ["control_input_not_mapping"]
    if _contains_non_finite(request):
        return ["input_non_finite"]
    errors: list[str] = []
    unknown = sorted((field for field in request if field not in _REQUEST_FIELDS), key=repr)
    missing = sorted(_REQUEST_FIELDS - set(request))
    errors.extend(f"unknown_input_field:{field}" for field in unknown)
    errors.extend(f"missing_input_field:{field}" for field in missing)
    if errors:
        return errors
    if not isinstance(request["action"], str) or request["action"] not in ACTION_KINDS:
        errors.append("action_invalid")
    if request["units"] != NORMALIZED_UNITS:
        errors.append("units_not_supported")
    return errors


def evaluate_control_request(state: SafetyState, request: Mapping[str, Any]) -> SafetyDecision:
    """Evaluate an offline or future entity-control intent without side effects.

    The offline simulation exception is explicit: it may run only in SIMULATION
    mode and never sets either permission field.  All entity-control requests
    require HARDWARE_CONTROL plus every fail-closed gate below.
    """

    request_errors = _validate_request(request)
    action = request.get("action") if isinstance(request, Mapping) else "<invalid>"
    mode = state.hardware_mode if isinstance(state, SafetyState) else "<invalid>"
    if request_errors:
        return SafetyDecision(False, tuple(request_errors), str(action), False, str(mode))

    state_errors = validate_safety_state(state)
    if state_errors:
        return SafetyDecision(False, tuple(state_errors), str(action), False, str(mode))

    if action == ACTION_OFFLINE_SIMULATION:
        if state.hardware_mode != SIMULATION:
            return SafetyDecision(False, ("offline_simulation_requires_simulation_mode",), action, False, state.hardware_mode)
        return SafetyDecision(True, ("offline_simulation_allowed",), action, False, state.hardware_mode)

    reasons: list[str] = []
    if state.hardware_mode != HARDWARE_CONTROL:
        reasons.append("hardware_control_mode_not_explicit")
    if state.h1_status != "PASS":
        reasons.append("h1_status_not_pass")
    if state.emergency_stop:
        reasons.append("emergency_stop_active")
    if not state.feedback_valid:
        reasons.append("feedback_invalid")
    if float(state.feedback_age_ms) > MAX_FEEDBACK_AGE_MS:
        reasons.append("feedback_expired")
    if state.watchdog_state != "OK":
        reasons.append("watchdog_timeout")
    if state.limit_state != "CLEAR":
        reasons.append("limit_state_abnormal")
    if state.collision_state != "CLEAR":
        reasons.append("collision_state_abnormal")
    if not state.entity_action_authorized:
        reasons.append("entity_action_not_authorized")
    if not state.execution_allowed:
        reasons.append("execution_not_allowed")
    return SafetyDecision(not reasons, tuple(reasons), action, state.execution_allowed and not reasons, state.hardware_mode)


def authorize_control(state: SafetyState, request: Mapping[str, Any]) -> SafetyDecision:
    """Compatibility name for future callers; this function still only judges."""

    return evaluate_control_request(state, request)


__all__ = [
    "ACTION_ENTITY_CONTROL",
    "ACTION_OFFLINE_SIMULATION",
    "HARDWARE_CONTROL",
    "HARDWARE_READONLY",
    "MAX_FEEDBACK_AGE_MS",
    "NORMALIZED_UNITS",
    "RUN_MODES",
    "SIMULATION",
    "SafetyDecision",
    "SafetyState",
    "authorize_control",
    "evaluate_control_request",
    "validate_safety_state",
]
