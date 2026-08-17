#!/usr/bin/env python3
"""Build a deterministic, offline B3 audit report.

The generator deliberately accepts only explicitly named JSON inputs.  It does
not inspect git, discover files, contact a service, or access hardware.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable


REPORT_SCHEMA = "b3.audit-report.v1"
EVENT_SCHEMA = "b3.audit-events.v1"
GENESIS = "sha256:" + "0" * 64
ALLOWED_EVENT_TYPES = {
    "source_snapshot",
    "build_artifacts_verified",
    "configuration_inputs_verified",
    "readiness_attestation_observed",
    "k0_simulation_observed",
    "camera_candidate_observed",
    "test_results_observed",
    "operator_confirmation_recorded",
    "entity_access_declared",
}
ALLOWED_EVIDENCE_KINDS = {"simulated", "offline_fixture"}
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class AuditError(Exception):
    """A deterministic input validation error."""


def canonical(value: Any) -> bytes:
    """Return the contract's canonical UTF-8 JSON representation."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AuditError(f"non-canonical JSON value: {exc}") from exc


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
    except OSError as exc:
        raise AuditError(f"cannot read explicit input {path}: {exc}") from exc
    return "sha256:" + h.hexdigest()


def load_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid {label} JSON: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditError(f"{label} must be an object")
    return value


def require_string(obj: dict[str, Any], key: str, label: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise AuditError(f"{label}.{key} must be a non-empty string")
    return value


def require_bool(obj: dict[str, Any], key: str, label: str, expected: bool | None = None) -> bool:
    value = obj.get(key)
    if not isinstance(value, bool):
        raise AuditError(f"{label}.{key} must be boolean")
    if expected is not None and value is not expected:
        raise AuditError(f"{label}.{key} must be {str(expected).lower()}")
    return value


def normalized_hash(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise AuditError(f"{label} must be a SHA-256 string")
    candidate = value if value.startswith("sha256:") else "sha256:" + value
    if not SHA256_RE.fullmatch(candidate):
        raise AuditError(f"{label} must be sha256:<64 lowercase hex>")
    return candidate


def hash_map(value: Any, label: str) -> dict[str, str]:
    """Accept the mapping and the common [{name, sha256}] form."""
    result: dict[str, str] = {}
    if isinstance(value, dict):
        entries: Iterable[tuple[Any, Any]] = value.items()
    elif isinstance(value, list):
        pairs = []
        for item in value:
            item_obj = require_object(item, label + "[]")
            name = item_obj.get("name", item_obj.get("logical_name"))
            hash_value = item_obj.get("sha256", item_obj.get("hash"))
            pairs.append((name, hash_value))
        entries = pairs
    else:
        raise AuditError(f"{label} must be an object or list")
    for name, hash_value in entries:
        if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name:
            raise AuditError(f"{label} contains an invalid logical name")
        if name in result:
            raise AuditError(f"{label} contains duplicate name {name}")
        result[name] = normalized_hash(hash_value, f"{label}.{name}")
    return dict(sorted(result.items()))


def fixed_false_fields(obj: dict[str, Any], label: str) -> None:
    for key in (
        "motor_command_written",
        "execution_allowed",
        "entity_action_authorized",
        "nano_deployment_authorized",
    ):
        require_bool(obj, key, label, False)


def validate_manifest(value: Any) -> dict[str, Any]:
    obj = require_object(value, "manifest")
    if obj.get("schema_version") != "b3.audit-manifest.v1":
        raise AuditError("manifest.schema_version is not b3.audit-manifest.v1")
    source_commit = require_string(obj, "source_commit", "manifest")
    artifacts_value = obj.get("build_artifact_hashes", obj.get("build_artifacts"))
    configs_value = obj.get("config_hashes")
    inputs_value = obj.get("input_hashes")
    if artifacts_value is None or configs_value is None or inputs_value is None:
        raise AuditError("manifest is missing build_artifact_hashes/config_hashes/input_hashes")
    artifacts = hash_map(artifacts_value, "manifest.build_artifact_hashes")
    configs = hash_map(configs_value, "manifest.config_hashes")
    inputs = hash_map(inputs_value, "manifest.input_hashes")
    if not artifacts or not configs or not inputs:
        raise AuditError("manifest hash collections must be non-empty")
    declaration = require_object(obj.get("entity_access_declaration"), "manifest.entity_access_declaration")
    validate_entity_declaration(declaration)
    return {
        "source_commit": source_commit,
        "build_artifact_hashes": artifacts,
        "config_hashes": configs,
        "input_hashes": inputs,
        "entity_access_declaration": {
            key: declaration[key]
            for key in (
                "nano_deployed",
                "entity_serial_accessed",
                "entity_d405_accessed",
                "motors_enabled",
                "motors_zeroed",
                "motors_moved",
            )
        },
    }


def validate_entity_declaration(value: dict[str, Any]) -> None:
    required = (
        "nano_deployed",
        "entity_serial_accessed",
        "entity_d405_accessed",
        "motors_enabled",
        "motors_zeroed",
        "motors_moved",
    )
    for key in required:
        require_bool(value, key, "entity_access_declaration", False)


def validate_readiness(value: Any) -> dict[str, Any]:
    obj = require_object(value, "readiness")
    if obj.get("schema_version") != "b3.v1":
        raise AuditError("readiness.schema_version is not b3.v1")
    fixed_false_fields(obj, "readiness")
    if obj.get("authorization_scope") != "software_precheck_only":
        raise AuditError("readiness.authorization_scope must be software_precheck_only")
    require_bool(obj, "ok", "readiness")
    require_string(obj, "attestation_id", "readiness")
    for key in ("issued_at_ms", "expires_at_ms"):
        if not isinstance(obj.get(key), int) or isinstance(obj.get(key), bool):
            raise AuditError(f"readiness.{key} must be an integer")
    if obj["expires_at_ms"] < obj["issued_at_ms"] or obj["expires_at_ms"] - obj["issued_at_ms"] > 300_000:
        raise AuditError("readiness validity exceeds 300 seconds or is inverted")
    source_state = require_object(obj.get("source_state"), "readiness.source_state")
    for key in ("command_seq", "target_command_seq", "endpoint_target_seq"):
        if not isinstance(source_state.get(key), int) or isinstance(source_state.get(key), bool):
            raise AuditError(f"readiness.source_state.{key} must be an integer")
    require_string(obj, "source_fingerprint", "readiness")
    require_string(obj, "software_commit", "readiness")
    if not isinstance(obj.get("config_hashes"), (dict, list)):
        raise AuditError("readiness.config_hashes must be a hash collection")
    hash_map(obj["config_hashes"], "readiness.config_hashes")
    if not isinstance(obj.get("checks"), list) or not isinstance(obj.get("blocking_reasons"), list):
        raise AuditError("readiness.checks and blocking_reasons must be arrays")
    return obj


def validate_k0(value: Any) -> dict[str, Any]:
    obj = require_object(value, "k0")
    if obj.get("schema_version") != "b3.k0-prepare-sim.v1":
        raise AuditError("k0.schema_version is not b3.k0-prepare-sim.v1")
    fixed_false_fields(obj, "k0")
    for key in ("state_trace", "operator_confirmation_points", "stop_reasons"):
        if not isinstance(obj.get(key), list):
            raise AuditError(f"k0.{key} must be an array")
    if not isinstance(obj.get("final_safe_state"), bool):
        raise AuditError("k0.final_safe_state must be boolean")
    return obj


def validate_camera(value: Any) -> dict[str, Any]:
    obj = require_object(value, "camera")
    if obj.get("schema_version") != "b3.camera-extrinsics-candidate.v1":
        raise AuditError("camera.schema_version is not b3.camera-extrinsics-candidate.v1")
    fixed_false_fields(obj, "camera")
    require_bool(obj, "formal_use_allowed", "camera", False)
    require_bool(obj, "promotion_locked", "camera", True)
    require_string(obj, "candidate_id", "camera")
    for key in ("fit_input_hashes", "validation_input_hashes"):
        hash_map(obj.get(key), f"camera.{key}")
    return obj


def validate_test_results(value: Any) -> dict[str, Any]:
    obj = require_object(value, "test_results")
    if obj.get("schema_version") != "b3.audit-test-results.v1":
        raise AuditError("test_results.schema_version is not b3.audit-test-results.v1")
    fixed_false_fields(obj, "test_results")
    if not isinstance(obj.get("results"), list):
        raise AuditError("test_results.results must be an array")
    return obj


def validate_events(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("schema_version") != EVENT_SCHEMA:
            raise AuditError("events.schema_version is not b3.audit-events.v1")
        events_value = value.get("events")
    else:
        events_value = value
    if not isinstance(events_value, list) or not events_value:
        raise AuditError("events must be a non-empty array")
    events: list[dict[str, Any]] = []
    previous = GENESIS
    last_time = -1
    for expected_sequence, raw in enumerate(events_value, 1):
        event = require_object(raw, f"event[{expected_sequence}]")
        if event.get("sequence") != expected_sequence:
            raise AuditError("event sequence is not continuous")
        if event.get("event_type") not in ALLOWED_EVENT_TYPES:
            raise AuditError(f"unknown event type: {event.get('event_type')}")
        occurred = event.get("occurred_at_ms")
        if not isinstance(occurred, int) or isinstance(occurred, bool) or occurred < last_time:
            raise AuditError("event timestamps must be nondecreasing integers")
        last_time = occurred
        if not isinstance(event.get("source"), str) or not event["source"]:
            raise AuditError("event source must be a non-empty string")
        if event.get("evidence_kind") not in ALLOWED_EVIDENCE_KINDS:
            raise AuditError("event evidence_kind is not allowed in B3")
        if "payload" not in event or not isinstance(event["payload"], dict):
            raise AuditError("event payload must be an object")
        if event.get("previous_event_hash") != previous:
            raise AuditError("event previous_event_hash breaks the chain")
        supplied_hash = event.get("event_hash")
        if not isinstance(supplied_hash, str) or not SHA256_RE.fullmatch(supplied_hash):
            raise AuditError("event_hash must be sha256:<64 lowercase hex>")
        unsigned = dict(event)
        unsigned.pop("event_hash", None)
        expected_hash = digest(unsigned)
        if supplied_hash != expected_hash:
            raise AuditError("event_hash does not match canonical event")
        events.append(event)
        previous = supplied_hash
    return events


def logical_name(value: str) -> str:
    # Paths never belong in the report core. Keep only a stable basename for
    # accidental path-like source labels.
    if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
        return os.path.basename(value.replace("\\", "/"))
    return value


def event_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sequence": event["sequence"],
            "event_type": event["event_type"],
            "occurred_at_ms": event["occurred_at_ms"],
            "source": logical_name(event["source"]),
            "evidence_kind": event["evidence_kind"],
            "previous_event_hash": event["previous_event_hash"],
            "event_hash": event["event_hash"],
            "payload_hash": digest(event["payload"]),
        }
        for event in events
    ]


def verify_manifest_files(manifest_obj: dict[str, Any], explicit_files: list[str]) -> None:
    expected: dict[str, str] = manifest_obj["input_hashes"]
    pairs: list[tuple[str, Path]] = []
    for item in explicit_files:
        if "=" not in item:
            raise AuditError("--input-file must be NAME=PATH")
        name, raw_path = item.split("=", 1)
        if name not in expected:
            raise AuditError(f"explicit input {name} is not declared in manifest.input_hashes")
        pairs.append((name, Path(raw_path)))
    # A manifest may carry an explicit input_files list; these are still read
    # only because the paths are supplied by the manifest, never discovered.
    for item in manifest_obj.get("_raw", {}).get("input_files", []):
        item_obj = require_object(item, "manifest.input_files[]")
        name = item_obj.get("name", item_obj.get("logical_name"))
        raw_path = item_obj.get("path")
        if isinstance(name, str) and isinstance(raw_path, str):
            pairs.append((name, Path(raw_path)))
    seen: set[str] = set()
    for name, path in pairs:
        if name in seen:
            raise AuditError(f"duplicate explicit input {name}")
        seen.add(name)
        if file_digest(path) != expected[name]:
            raise AuditError(f"input hash mismatch for {name}")
    if expected and seen != set(expected):
        missing = sorted(set(expected) - seen)
        raise AuditError("missing explicit input files: " + ", ".join(missing))


def build_report(manifest: dict[str, Any], readiness: dict[str, Any], k0: dict[str, Any], camera: dict[str, Any], tests: dict[str, Any], events: list[dict[str, Any]], errors: list[str]) -> dict[str, Any]:
    core: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA,
        "valid": not errors,
        "motor_command_written": False,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "source_commit": manifest.get("source_commit", ""),
        "build_artifact_hashes": manifest.get("build_artifact_hashes", {}),
        "config_hashes": manifest.get("config_hashes", {}),
        "input_hashes": manifest.get("input_hashes", {}),
        "readiness_summary": {
            "schema_version": readiness.get("schema_version"),
            "ok": readiness.get("ok"),
            "attestation_id": readiness.get("attestation_id"),
            "issued_at_ms": readiness.get("issued_at_ms"),
            "expires_at_ms": readiness.get("expires_at_ms"),
            "software_commit": readiness.get("software_commit"),
            "checks": readiness.get("checks", []),
            "blocking_reasons": readiness.get("blocking_reasons", []),
        },
        "k0_simulation_summary": {
            "schema_version": k0.get("schema_version"),
            "final_safe_state": k0.get("final_safe_state"),
            "state_trace": k0.get("state_trace", []),
            "operator_confirmation_points": k0.get("operator_confirmation_points", []),
            "stop_reasons": k0.get("stop_reasons", []),
        },
        "camera_candidate_summary": {
            "schema_version": camera.get("schema_version"),
            "candidate_id": camera.get("candidate_id"),
            "formal_use_allowed": False,
            "promotion_locked": True,
            "execution_allowed": False,
            "fit_input_hashes": hash_map(camera.get("fit_input_hashes", {}), "camera.fit_input_hashes"),
            "validation_input_hashes": hash_map(camera.get("validation_input_hashes", {}), "camera.validation_input_hashes"),
        },
        "events": event_summary(events),
        "event_chain": {
            "schema_version": EVENT_SCHEMA,
            "genesis_previous_event_hash": GENESIS,
            "event_count": len(events),
            "head_event_hash": events[-1]["event_hash"] if events else GENESIS,
        },
        "test_results": tests.get("results", []),
        "entity_access_declaration": manifest.get("entity_access_declaration", {}),
    }
    if errors:
        core["blocking_reasons"] = sorted(set(errors))
    report_hash = hashlib.sha256(canonical(core)).hexdigest()
    report = dict(core)
    report["report_id"] = "b3-audit-" + report_hash[:16]
    report["report_hash"] = report_hash
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--k0", required=True, type=Path)
    parser.add_argument("--camera", required=True, type=Path)
    parser.add_argument("--test-results", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--output", "--out", required=True, type=Path)
    parser.add_argument("--input-file", action="append", default=[], metavar="NAME=PATH")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    errors: list[str] = []
    manifest: dict[str, Any] = {}
    readiness: dict[str, Any] = {}
    k0: dict[str, Any] = {}
    camera: dict[str, Any] = {}
    tests: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    try:
        raw_manifest = load_json(args.manifest, "manifest")
        manifest = validate_manifest(raw_manifest)
        manifest["_raw"] = raw_manifest
        verify_manifest_files(manifest, args.input_file)
        readiness = validate_readiness(load_json(args.readiness, "readiness"))
        k0 = validate_k0(load_json(args.k0, "k0"))
        camera = validate_camera(load_json(args.camera, "camera"))
        tests = validate_test_results(load_json(args.test_results, "test_results"))
        events = validate_events(load_json(args.events, "events"))
    except AuditError as exc:
        errors.append(str(exc))
    except Exception as exc:  # fail closed while still emitting an invalid report
        errors.append(f"unexpected validation error: {exc}")
    report = build_report(manifest, readiness, k0, camera, tests, events, errors)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"cannot write report: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("invalid B3 audit report: " + "; ".join(errors), file=sys.stderr)
        return 1
    print(report["report_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
