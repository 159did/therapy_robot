#!/usr/bin/env python3
"""Build a deterministic, offline-only B4-PREP-D safety package.

This module validates explicit B3 camera-candidate inputs and creates a
non-promotable V2-F gate report. It never discovers files, opens hardware,
starts a process, writes a calibration file, or emits a motor target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CANDIDATE_SCHEMA = "b3.camera-extrinsics-candidate.v1"
DATASET_SCHEMA = "b3.camera-samples.v1"
QUALITY_SCHEMA = "b2.vision-quality.v1"
GATE_SCHEMA = "b4.prep.d.v2f-promotion-gate.v1"
MAX_AGE_MS = 300_000
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class SafetyInputError(ValueError):
    pass


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SafetyInputError(f"non_canonical_value:{exc}") from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise SafetyInputError(f"file_read_failed:{exc}") from exc
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SafetyInputError(f"{label}_json_invalid:{exc}") from exc
    if not isinstance(value, dict):
        raise SafetyInputError(f"{label}_not_object")
    return value


def nonempty_string(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not value:
        raise SafetyInputError(reason)
    return value


def hash_value(value: Any, reason: str) -> str:
    if not isinstance(value, str):
        raise SafetyInputError(reason)
    normalized = value.removeprefix("sha256:")
    if not HASH_RE.fullmatch(normalized):
        raise SafetyInputError(reason)
    return normalized


def fixed_false(obj: dict[str, Any], keys: tuple[str, ...], prefix: str) -> None:
    for key in keys:
        if obj.get(key) is not False:
            raise SafetyInputError(f"{prefix}_{key}_must_be_false")


def parse_time(value: Any, reason: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SafetyInputError(reason)
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SafetyInputError(reason) from exc
    if parsed.tzinfo is None:
        raise SafetyInputError(reason)
    return parsed.astimezone(timezone.utc)


def finite_vector(value: Any, reason: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise SafetyInputError(reason)
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise SafetyInputError(reason)
        result.append(float(item))
    return result


def load_dataset(path: Path, label: str) -> tuple[dict[str, Any], str, set[str], list[datetime]]:
    data = load_json(path, label)
    if data.get("schema_version") != DATASET_SCHEMA:
        raise SafetyInputError(f"{label}_schema_invalid")
    if data.get("dataset_kind") != "measurement_candidate":
        raise SafetyInputError(f"{label}_kind_invalid")
    batch_id = nonempty_string(data.get("batch_id"), f"{label}_batch_id_missing")
    frames = data.get("coordinate_frames")
    units = data.get("units")
    if not isinstance(frames, dict) or frames.get("source") != "d405_camera" or frames.get("target") != "robot_base":
        raise SafetyInputError(f"{label}_coordinate_frames_invalid")
    if not isinstance(units, dict) or units.get("points") != "m":
        raise SafetyInputError(f"{label}_units_invalid")
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise SafetyInputError(f"{label}_samples_missing")
    ids: set[str] = set()
    times: list[datetime] = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise SafetyInputError(f"{label}_sample_invalid")
        sample_id = nonempty_string(sample.get("sample_id", sample.get("name")), f"{label}_sample_id_invalid")
        if sample_id in ids:
            raise SafetyInputError(f"{label}_sample_id_duplicate")
        ids.add(sample_id)
        finite_vector(sample.get("camera_point_m"), f"{label}_camera_point_invalid")
        finite_vector(sample.get("robot_point_m"), f"{label}_robot_point_invalid")
        times.append(parse_time(sample.get("timestamp_utc", data.get("captured_at_utc")), f"{label}_timestamp_invalid"))
    if any(right <= left for left, right in zip(times, times[1:])):
        raise SafetyInputError(f"{label}_timestamp_not_strictly_increasing")
    return data, batch_id, ids, times


def load_quality(path: Path) -> tuple[dict[str, Any], str]:
    data = load_json(path, "quality")
    if data.get("schema_version") != QUALITY_SCHEMA or data.get("quality_valid") is not True:
        raise SafetyInputError("quality_invalid")
    fixed_false(data, ("formal_use_allowed", "execution_allowed"), "quality")
    reasons = data.get("blocking_reasons")
    checks = data.get("checks")
    if not isinstance(reasons, list) or reasons:
        raise SafetyInputError("quality_blocking_reasons")
    if not isinstance(checks, list) or any(not isinstance(item, dict) or item.get("status") != "pass" for item in checks):
        raise SafetyInputError("quality_checks_not_all_pass")
    return data, sha256_file(path)


def validate_candidate(candidate: dict[str, Any], candidate_hash: str) -> None:
    if candidate.get("schema_version") != CANDIDATE_SCHEMA:
        raise SafetyInputError("candidate_schema_invalid")
    nonempty_string(candidate.get("candidate_id"), "candidate_id_missing")
    if candidate.get("candidate_valid") is not True:
        raise SafetyInputError("candidate_not_valid")
    fixed_false(candidate, ("formal_use_allowed", "execution_allowed", "entity_action_authorized", "nano_deployment_authorized"), "candidate")
    if candidate.get("promotion_locked") is not True:
        raise SafetyInputError("candidate_promotion_lock_missing")
    for key in ("fit_input", "validation_input", "quality_binding"):
        if not isinstance(candidate.get(key), dict):
            raise SafetyInputError(f"candidate_{key}_missing")
    if hash_value(candidate["fit_input"].get("sha256"), "candidate_fit_hash_invalid") == candidate_hash:
        raise SafetyInputError("candidate_hash_unexpected")


def validate_gate(
    candidate: dict[str, Any], fit: dict[str, Any], validation: dict[str, Any], quality: dict[str, Any],
    *, candidate_hash: str, fit_hash: str, validation_hash: str, quality_hash: str,
    fit_ids: set[str], validation_ids: set[str], fit_batch: str, validation_batch: str,
    validation_times: list[datetime], reference_time: datetime, max_age_ms: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    try:
        validate_candidate(candidate, candidate_hash)
    except SafetyInputError as exc:
        reasons.append(str(exc))
    candidate_fit = candidate.get("fit_input") if isinstance(candidate.get("fit_input"), dict) else {}
    candidate_validation = candidate.get("validation_input") if isinstance(candidate.get("validation_input"), dict) else {}
    candidate_quality = candidate.get("quality_binding") if isinstance(candidate.get("quality_binding"), dict) else {}
    if candidate_fit.get("sha256", "").removeprefix("sha256:") != fit_hash:
        reasons.append("fit_input_hash_mismatch")
    if candidate_validation.get("sha256", "").removeprefix("sha256:") != validation_hash:
        reasons.append("validation_input_hash_mismatch")
    if candidate_quality.get("sha256", "").removeprefix("sha256:") != quality_hash:
        reasons.append("quality_hash_mismatch")
    if candidate_fit.get("batch_id") != fit_batch:
        reasons.append("fit_batch_id_mismatch")
    if candidate_validation.get("batch_id") != validation_batch:
        reasons.append("validation_batch_id_mismatch")
    if fit_batch == validation_batch:
        reasons.append("batch_id_reused")
    candidate_fit_ids = candidate_fit.get("sample_ids")
    if not isinstance(candidate_fit_ids, list) or set(candidate_fit_ids) != fit_ids:
        reasons.append("fit_sample_ids_mismatch")
    if fit_ids & validation_ids:
        reasons.append("sample_id_reused")
    if candidate_quality.get("schema_version") != QUALITY_SCHEMA:
        reasons.append("quality_schema_binding_mismatch")
    for timestamp in validation_times:
        age_ms = (reference_time - timestamp).total_seconds() * 1000
        if age_ms < 0:
            reasons.append("validation_timestamp_in_future")
        elif age_ms > max_age_ms:
            reasons.append("validation_timestamp_too_old")
    # Keep the argument visible to callers and make malformed quality input a
    # gate failure even when a caller bypasses load_quality.
    if quality.get("quality_valid") is not True:
        reasons.append("quality_not_valid")
    return not reasons, sorted(set(reasons))


def logical_hash(name: str, value: str) -> dict[str, str]:
    return {"name": name, "sha256": value}


def build_report(
    *, valid: bool, reasons: list[str], candidate: dict[str, Any], candidate_hash: str,
    fit_hash: str, validation_hash: str, quality_hash: str, fit_batch: str,
    validation_batch: str, fit_ids: set[str], validation_ids: set[str],
    reference_time: datetime, max_age_ms: int,
) -> dict[str, Any]:
    core: dict[str, Any] = {
        "schema_version": GATE_SCHEMA,
        "valid": valid,
        "formal_use_allowed": False,
        "promotion_locked": True,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "human_contact_allowed": False,
        "entity_camera_accessed": False,
        "candidate_summary": {
            "candidate_id": candidate.get("candidate_id"),
            "candidate_valid": candidate.get("candidate_valid"),
            "candidate_hash": candidate_hash,
            "fit_input_hash": fit_hash,
            "validation_input_hash": validation_hash,
            "quality_hash": quality_hash,
            "fit_batch_id": fit_batch,
            "validation_batch_id": validation_batch,
            "fit_sample_count": len(fit_ids),
            "validation_sample_count": len(validation_ids),
            "datasets_disjoint": fit_batch != validation_batch and not (fit_ids & validation_ids),
        },
        "promotion_gate": {
            "required": ["candidate_valid", "dataset_independence", "quality_valid", "validation_fresh"],
            "blocking_reasons": reasons,
            "reference_time": reference_time.isoformat().replace("+00:00", "Z"),
            "max_age_ms": max_age_ms,
        },
        "input_hashes": [
            logical_hash("candidate", candidate_hash),
            logical_hash("fit", fit_hash),
            logical_hash("validation", validation_hash),
            logical_hash("quality", quality_hash),
        ],
    }
    report_hash = sha256_bytes(canonical(core))
    return {**core, "report_id": "b4-d-gate-" + report_hash[:16], "report_hash": report_hash}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--fit-input", required=True, type=Path)
    parser.add_argument("--validation-input", required=True, type=Path)
    parser.add_argument("--quality-report", required=True, type=Path)
    parser.add_argument("--reference-time", required=True, help="RFC3339 UTC timestamp")
    parser.add_argument("--max-age-ms", type=int, default=MAX_AGE_MS)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    errors: list[str] = []
    candidate: dict[str, Any] = {}
    fit: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    candidate_hash = fit_hash = validation_hash = quality_hash = ""
    fit_batch = validation_batch = ""
    fit_ids: set[str] = set()
    validation_ids: set[str] = set()
    validation_times: list[datetime] = []
    try:
        if args.max_age_ms < 0 or args.max_age_ms > MAX_AGE_MS:
            raise SafetyInputError("max_age_exceeds_300_seconds")
        reference_time = parse_time(args.reference_time, "reference_time_invalid")
        candidate = load_json(args.candidate, "candidate")
        candidate_hash = sha256_file(args.candidate)
        fit, fit_batch, fit_ids, _ = load_dataset(args.fit_input, "fit")
        validation, validation_batch, validation_ids, validation_times = load_dataset(args.validation_input, "validation")
        quality, quality_hash = load_quality(args.quality_report)
        fit_hash = sha256_file(args.fit_input)
        validation_hash = sha256_file(args.validation_input)
        valid, reasons = validate_gate(
            candidate, fit, validation, quality,
            candidate_hash=candidate_hash, fit_hash=fit_hash, validation_hash=validation_hash,
            quality_hash=quality_hash, fit_ids=fit_ids, validation_ids=validation_ids,
            fit_batch=fit_batch, validation_batch=validation_batch, validation_times=validation_times,
            reference_time=reference_time, max_age_ms=args.max_age_ms,
        )
        errors.extend(reasons)
    except (SafetyInputError, OSError, ValueError) as exc:
        errors.append(str(exc))
        try:
            reference_time = parse_time(args.reference_time, "reference_time_invalid")
        except SafetyInputError:
            reference_time = datetime.fromtimestamp(0, tz=timezone.utc)
    report = build_report(
        valid=not errors, reasons=sorted(set(errors)), candidate=candidate, candidate_hash=candidate_hash,
        fit_hash=fit_hash, validation_hash=validation_hash, quality_hash=quality_hash,
        fit_batch=fit_batch, validation_batch=validation_batch, fit_ids=fit_ids,
        validation_ids=validation_ids, reference_time=reference_time, max_age_ms=args.max_age_ms,
    )
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"output_write_failed:{exc}", file=sys.stderr)
        return 2
    if errors:
        print("invalid V2-F promotion gate: " + "; ".join(sorted(set(errors))), file=sys.stderr)
        return 1
    print(report["report_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
