#!/usr/bin/env python3
"""Fail-closed, offline-only entity-window authorization contract.

This module deliberately contains no transport, process, serial, shared-memory,
or motor-control code. It creates and validates a *prepared* software package;
an external safety process must issue any real entity-window authorization.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "b4.prep.a.v1"
MAX_WINDOW_MS = 300_000
ALLOWED_STATUS = frozenset({"PREPARED", "REQUESTED", "AUTHORIZED"})

REQUIRED_FIELDS = (
    "schema_version", "contract_id", "status", "window_id", "scope",
    "issued_at_ms", "expires_at_ms", "revoked", "revocation_reason",
    "operator_confirmation", "rollback_owner", "evidence_manifest",
    "entity_access_declaration", "execution_allowed",
    "entity_action_authorized", "nano_deployment_authorized",
)
ENTITY_ACCESS_KEYS = ("serial", "d405", "nano_deployment")
_REQUIRED_SET = frozenset(REQUIRED_FIELDS)


def canonical_json(value: Any) -> str:
    """Return deterministic JSON used for IDs and evidence fingerprints."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(evidence: Mapping[str, bytes]) -> list[dict[str, str]]:
    return [{"name": name, "sha256": _sha256_bytes(evidence[name])} for name in sorted(evidence)]


def _identity_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(contract)
    payload.pop("contract_id", None)
    return payload


def contract_id_for(contract: Mapping[str, Any]) -> str:
    """Calculate the stable ID from every contract field except ``contract_id``."""
    return hashlib.sha256(canonical_json(_identity_payload(contract)).encode("utf-8")).hexdigest()


def build_prepared_contract(
    *, window_id: str, scope: list[str] | tuple[str, ...], issued_at_ms: int,
    rollback_owner: str, evidence: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Build a deterministic PREPARED package with every action gate false."""
    evidence = {} if evidence is None else evidence
    normalized_scope = sorted({str(item) for item in scope})
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "contract_id": "", "status": "PREPARED",
        "window_id": str(window_id), "scope": normalized_scope,
        "issued_at_ms": int(issued_at_ms), "expires_at_ms": int(issued_at_ms) + MAX_WINDOW_MS,
        "revoked": False, "revocation_reason": "",
        "operator_confirmation": {"confirmed": False, "operator_id": "", "confirmed_at_ms": None},
        "rollback_owner": str(rollback_owner), "evidence_manifest": _manifest(evidence),
        "entity_access_declaration": {key: False for key in ENTITY_ACCESS_KEYS},
        "execution_allowed": False, "entity_action_authorized": False,
        "nano_deployment_authorized": False,
    }
    contract["contract_id"] = contract_id_for(contract)
    return contract


def validate_contract(
    contract: Mapping[str, Any], *, now_ms: int | None = None,
    expected_scope: list[str] | tuple[str, ...] | None = None,
    evidence: Mapping[str, bytes] | None = None, allow_authorized: bool = False,
) -> tuple[bool, list[str]]:
    """Validate a package without side effects; every error is fail-closed."""
    errors: list[str] = []
    if not isinstance(contract, Mapping):
        return False, ["contract_not_mapping"]
    keys = set(contract)
    missing = sorted(_REQUIRED_SET - keys)
    unknown = sorted(keys - _REQUIRED_SET)
    errors.extend(f"missing:{key}" for key in missing)
    errors.extend(f"unknown:{key}" for key in unknown)
    if errors:
        return False, errors

    if contract["schema_version"] != SCHEMA_VERSION:
        errors.append("schema_version_not_supported")
    status = contract["status"]
    if not isinstance(status, str) or status not in ALLOWED_STATUS:
        errors.append("status_not_supported")
    if status == "AUTHORIZED" and not allow_authorized:
        errors.append("authorized_status_forbidden_in_b4_prep")
    if not isinstance(contract["window_id"], str) or not contract["window_id"]:
        errors.append("window_id_invalid")
    scope = contract["scope"]
    if not isinstance(scope, list) or not scope or any(not isinstance(item, str) or not item for item in scope):
        errors.append("scope_invalid")
    elif scope != sorted(set(scope)):
        errors.append("scope_not_normalized")
    if expected_scope is not None and isinstance(scope, list) and all(isinstance(item, str) for item in scope) and set(scope) != set(expected_scope):
        errors.append("scope_mismatch")

    issued, expires = contract["issued_at_ms"], contract["expires_at_ms"]
    if not isinstance(issued, int) or isinstance(issued, bool):
        errors.append("issued_at_ms_invalid")
    if not isinstance(expires, int) or isinstance(expires, bool):
        errors.append("expires_at_ms_invalid")
    if isinstance(issued, int) and not isinstance(issued, bool) and isinstance(expires, int) and not isinstance(expires, bool):
        if expires <= issued:
            errors.append("time_order_invalid")
        if expires - issued > MAX_WINDOW_MS:
            errors.append("window_exceeds_300_seconds")
        if now_ms is not None and (now_ms < issued or now_ms > expires):
            errors.append("window_not_active")

    if not isinstance(contract["revoked"], bool):
        errors.append("revoked_invalid")
    elif contract["revoked"]:
        errors.append("contract_revoked")
        if not isinstance(contract["revocation_reason"], str) or not contract["revocation_reason"]:
            errors.append("revocation_reason_required")
    elif contract["revocation_reason"] != "":
        errors.append("revocation_reason_must_be_empty")

    confirmation = contract["operator_confirmation"]
    if not isinstance(confirmation, Mapping) or set(confirmation) != {"confirmed", "operator_id", "confirmed_at_ms"}:
        errors.append("operator_confirmation_invalid")
    elif confirmation["confirmed"] is not False:
        errors.append("operator_confirmation_must_be_false_in_prep")
    if not isinstance(contract["rollback_owner"], str) or not contract["rollback_owner"]:
        errors.append("rollback_owner_invalid")

    manifest = contract["evidence_manifest"]
    if not isinstance(manifest, list):
        errors.append("evidence_manifest_invalid")
    else:
        names: list[str] = []
        for entry in manifest:
            if not isinstance(entry, Mapping) or set(entry) != {"name", "sha256"}:
                errors.append("evidence_entry_invalid")
                continue
            name, digest = entry["name"], entry["sha256"]
            if not isinstance(name, str) or not name or not isinstance(digest, str) or len(digest) != 64:
                errors.append("evidence_entry_invalid")
            if isinstance(name, str):
                names.append(name)
        if names != sorted(names) or len(names) != len(set(names)):
            errors.append("evidence_manifest_not_normalized")
        if evidence is not None and manifest != _manifest(evidence):
            errors.append("evidence_hash_mismatch")

    access = contract["entity_access_declaration"]
    if not isinstance(access, Mapping) or set(access) != set(ENTITY_ACCESS_KEYS) or any(value is not False for value in access.values()):
        errors.append("entity_access_not_false")
    for field in ("execution_allowed", "entity_action_authorized", "nano_deployment_authorized"):
        if contract[field] is not False:
            errors.append(f"{field}_must_be_false")
    try:
        calculated_id = contract_id_for(contract)
    except (TypeError, ValueError):
        calculated_id = None
        errors.append("contract_id_unserializable")
    if contract.get("contract_id") != calculated_id:
        errors.append("contract_id_mismatch")
    return not errors, errors


__all__ = ["MAX_WINDOW_MS", "SCHEMA_VERSION", "build_prepared_contract", "canonical_json", "contract_id_for", "validate_contract"]
