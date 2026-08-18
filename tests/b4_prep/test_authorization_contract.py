#!/usr/bin/env python3
"""Offline tests for B4-PREP-A-01; no hardware or runtime is touched."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from b4_prep.authorization_contract import (  # noqa: E402
    MAX_WINDOW_MS, SCHEMA_VERSION, build_prepared_contract, contract_id_for, validate_contract,
)


def prepared() -> dict:
    return build_prepared_contract(
        window_id="h1-offline-20260818-01", scope=["H1", "K0_READ_ONLY"],
        issued_at_ms=1_000_000, rollback_owner="safety-owner",
        evidence={"plan.md": b"offline plan\n", "risk.json": b"{}\n"},
    )


def assert_rejected(mutator, marker: str) -> None:
    value = prepared()
    mutator(value)
    ok, errors = validate_contract(value, now_ms=1_000_001)
    assert not ok, marker
    assert marker in errors, (marker, errors)


def test_valid_prepared_contract() -> None:
    value = prepared()
    ok, errors = validate_contract(value, now_ms=value["issued_at_ms"] + 1, expected_scope=["K0_READ_ONLY", "H1"], evidence={"plan.md": b"offline plan\n", "risk.json": b"{}\n"})
    assert ok, errors
    assert value["schema_version"] == SCHEMA_VERSION
    assert value["expires_at_ms"] - value["issued_at_ms"] == MAX_WINDOW_MS
    assert value["execution_allowed"] is False
    assert value["entity_action_authorized"] is False
    assert value["nano_deployment_authorized"] is False


def test_missing_unknown_and_schema_rejected() -> None:
    assert_rejected(lambda value: value.pop("rollback_owner"), "missing:rollback_owner")
    assert_rejected(lambda value: value.__setitem__("unexpected", 1), "unknown:unexpected")
    assert_rejected(lambda value: value.__setitem__("schema_version", "b4.unknown"), "schema_version_not_supported")


def test_time_and_clock_fail_closed() -> None:
    assert_rejected(lambda value: value.__setitem__("expires_at_ms", value["issued_at_ms"] + MAX_WINDOW_MS + 1), "window_exceeds_300_seconds")
    value = prepared()
    ok, errors = validate_contract(value, now_ms=value["issued_at_ms"] - 1)
    assert not ok and "window_not_active" in errors


def test_revocation_scope_and_permission_changes_rejected() -> None:
    assert_rejected(lambda value: value.__setitem__("revoked", True), "contract_revoked")
    value = prepared()
    ok, errors = validate_contract(value, now_ms=value["issued_at_ms"] + 1, expected_scope=["H1"])
    assert not ok and "scope_mismatch" in errors
    assert_rejected(lambda value: value["scope"].append("MOTOR_WRITE"), "contract_id_mismatch")
    assert_rejected(lambda value: value["entity_access_declaration"].__setitem__("serial", True), "entity_access_not_false")
    assert_rejected(lambda value: value.__setitem__("execution_allowed", True), "execution_allowed_must_be_false")
    assert_rejected(lambda value: value.__setitem__("entity_action_authorized", True), "entity_action_authorized_must_be_false")
    assert_rejected(lambda value: value.__setitem__("nano_deployment_authorized", True), "nano_deployment_authorized_must_be_false")


def test_evidence_hash_and_id_tamper_rejected() -> None:
    value = prepared()
    ok, errors = validate_contract(value, now_ms=value["issued_at_ms"] + 1, evidence={"plan.md": b"changed", "risk.json": b"{}\n"})
    assert not ok and "evidence_hash_mismatch" in errors
    value = prepared()
    value["rollback_owner"] = "other-owner"
    ok, errors = validate_contract(value, now_ms=value["issued_at_ms"] + 1)
    assert not ok and "contract_id_mismatch" in errors


def test_contract_id_is_deterministic_and_copy_safe() -> None:
    first = prepared()
    second = prepared()
    assert first["contract_id"] == second["contract_id"] == contract_id_for(first)
    assert copy.deepcopy(first) == second


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
