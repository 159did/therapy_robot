#!/usr/bin/env python3
"""Build a deterministic, non-promotable camera extrinsics candidate offline."""

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


SCHEMA_VERSION = "b3.camera-extrinsics-candidate.v1"
DATASET_SCHEMA = "b3.camera-samples.v1"
TOOL_VERSION = "b3-c.1"
FORMAL_NAMES = {"camera_to_base.json", "camera_to_base.candidate.json"}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp_missing")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc)


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("non_finite_" + name)
    return float(value)


def vector(value, name):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("invalid_" + name)
    return np.asarray([finite(item, name) for item in value], dtype=float)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_dataset(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != DATASET_SCHEMA:
        raise ValueError("dataset_schema_invalid")
    if data.get("dataset_kind") != "measurement_candidate":
        raise ValueError("dataset_kind_not_measurement_candidate")
    batch_id = data.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError("batch_id_missing")
    frames = data.get("coordinate_frames")
    units = data.get("units")
    if not isinstance(frames, dict) or frames.get("source") != "d405_camera" or frames.get("target") != "robot_base":
        raise ValueError("coordinate_frames_invalid")
    if not isinstance(units, dict) or units.get("points") != "m":
        raise ValueError("point_units_invalid")
    samples = data.get("samples")
    if not isinstance(samples, list) or len(samples) < 3:
        raise ValueError("sample_count_below_minimum")
    clean = []
    identifiers = set()
    timestamps = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError("sample_schema_invalid")
        sample_id = sample.get("sample_id", sample.get("name"))
        if not isinstance(sample_id, str) or not sample_id.strip() or sample_id in identifiers:
            raise ValueError("sample_id_missing_or_duplicate")
        identifiers.add(sample_id)
        camera = vector(sample.get("camera_point_m"), "camera_point_m")
        base = vector(sample.get("robot_point_m"), "robot_point_m")
        timestamp = sample.get("timestamp_utc", data.get("captured_at_utc"))
        timestamps.append(parse_timestamp(timestamp))
        item = {"sample_id": sample_id, "camera": camera, "base": base, "timestamp_utc": timestamp}
        if "camera_normal" in sample or "robot_normal" in sample:
            if "camera_normal" not in sample or "robot_normal" not in sample:
                raise ValueError("normal_pair_incomplete")
            item["camera_normal"] = vector(sample["camera_normal"], "camera_normal")
            item["robot_normal"] = vector(sample["robot_normal"], "robot_normal")
        clean.append(item)
    if any(right < left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("timestamp_order_invalid")
    return {"path": path, "data": data, "batch_id": batch_id, "samples": clean, "sha256": sha256_file(path), "sample_ids": identifiers, "timestamps": timestamps}


def check_time(dataset, reference_time, max_age_s):
    reference = parse_timestamp(reference_time)
    ages = [(reference - timestamp).total_seconds() for timestamp in dataset["timestamps"]]
    if any(age > max_age_s for age in ages):
        return False, "timestamp_too_old", max(ages)
    if any(age < 0 for age in ages):
        return False, "timestamp_in_future", max(ages)
    return True, "ok", max(ages)


def rigid_fit(samples):
    camera = np.asarray([item["camera"] for item in samples], dtype=float)
    base = np.asarray([item["base"] for item in samples], dtype=float)
    camera_mean = camera.mean(axis=0)
    base_mean = base.mean(axis=0)
    centered_camera = camera - camera_mean
    centered_base = base - base_mean
    singular = np.linalg.svd(centered_camera, compute_uv=False)
    rank = int(np.sum(singular > max(1e-9, singular[0] * 1e-4))) if singular.size else 0
    if rank < 2:
        raise ValueError("camera_point_rank_below_minimum")
    u, _, vt = np.linalg.svd(centered_camera.T @ centered_base)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    translation = base_mean - rotation @ camera_mean
    predicted = (rotation @ camera.T).T + translation
    errors = np.linalg.norm(predicted - base, axis=1)
    return rotation, translation, errors, rank


def load_quality(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "b2.vision-quality.v1":
        raise ValueError("b2_quality_schema_invalid")
    if data.get("quality_valid") is not True:
        raise ValueError("b2_quality_invalid")
    if data.get("formal_use_allowed") is not False or data.get("execution_allowed") is not False:
        raise ValueError("b2_quality_execution_flags_invalid")
    if data.get("blocking_reasons") or any(isinstance(item, dict) and item.get("status") != "pass" for item in data.get("checks", [])):
        raise ValueError("b2_quality_checks_not_all_pass")
    return {"path": path, "sha256": sha256_file(path), "data": data}


def canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_report(fit, validation, quality, args):
    fit_ok, fit_reason, fit_age = check_time(fit, args.reference_time, args.max_timestamp_age_s)
    validation_ok, validation_reason, validation_age = check_time(validation, args.reference_time, args.max_timestamp_age_s)
    reasons = []
    if fit["sha256"] == validation["sha256"]:
        reasons.append("input_hash_reused")
    if fit["batch_id"] == validation["batch_id"]:
        reasons.append("batch_id_reused")
    if fit["sample_ids"] & validation["sample_ids"]:
        reasons.append("sample_id_reused")
    if not fit_ok:
        reasons.append("fit_" + fit_reason)
    if not validation_ok:
        reasons.append("validation_" + validation_reason)
    rotation, translation, errors, rank = rigid_fit(fit["samples"])
    determinant = float(np.linalg.det(rotation))
    orthonormal_error = float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro"))
    fit_rmse_mm = float(np.sqrt(np.mean(errors ** 2)) * 1000.0)
    fit_max_mm = float(np.max(errors) * 1000.0)
    if fit_rmse_mm > args.max_fit_rmse_mm:
        reasons.append("fit_rmse_above_maximum")
    if fit_max_mm > args.max_fit_error_mm:
        reasons.append("fit_error_above_maximum")
    if abs(determinant - 1.0) > 1e-6 or orthonormal_error > 1e-6:
        reasons.append("rotation_not_rigid")
    core = {
        "schema_version": SCHEMA_VERSION,
        "fit_sha256": fit["sha256"],
        "validation_sha256": validation["sha256"],
        "quality_sha256": quality["sha256"],
        "fit_batch_id": fit["batch_id"],
        "validation_batch_id": validation["batch_id"],
        "thresholds": {"max_fit_rmse_mm": args.max_fit_rmse_mm, "max_fit_error_mm": args.max_fit_error_mm, "max_timestamp_age_s": args.max_timestamp_age_s},
        "rotation": [[float(value) for value in row] for row in rotation],
        "translation_m": [float(value) for value in translation],
    }
    candidate_valid = not reasons
    candidate_id = "camcand-" + hashlib.sha256(canonical(core).encode("utf-8")).hexdigest()[:24] if candidate_valid else None
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at_utc": utc_now(),
        "candidate_id": candidate_id,
        "candidate_valid": candidate_valid,
        "formal_use_allowed": False,
        "promotion_locked": True,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "fit_input": {"path": str(fit["path"]), "sha256": fit["sha256"], "batch_id": fit["batch_id"], "sample_count": len(fit["samples"]), "sample_ids": sorted(fit["sample_ids"])},
        "validation_input": {"path": str(validation["path"]), "sha256": validation["sha256"], "batch_id": validation["batch_id"], "sample_count": len(validation["samples"])},
        "quality_binding": {"path": str(quality["path"]), "sha256": quality["sha256"], "schema_version": quality["data"]["schema_version"], "quality_valid": True},
        "coordinate_frames": {"source": "d405_camera", "target": "robot_base"},
        "units": {"points": "m", "translation": "m", "residual": "mm"},
        "matrix": {"rotation": core["rotation"], "translation_m": core["translation_m"], "usage": "p_base = R @ p_camera + t"},
        "quality": {"thresholds": core["thresholds"], "metrics": {"fit_rmse_mm": fit_rmse_mm, "fit_max_error_mm": fit_max_mm, "fit_timestamp_age_s": fit_age, "validation_timestamp_age_s": validation_age, "camera_point_rank": rank, "rotation_determinant": determinant, "rotation_orthonormal_error": orthonormal_error}, "checks": [{"id": "dataset_independence", "status": "pass" if not (fit["batch_id"] == validation["batch_id"] or fit["sample_ids"] & validation["sample_ids"]) else "fail", "reason_code": "ok" if not (fit["batch_id"] == validation["batch_id"] or fit["sample_ids"] & validation["sample_ids"]) else "dataset_reused"}, {"id": "fit_quality", "status": "pass" if fit_rmse_mm <= args.max_fit_rmse_mm and fit_max_mm <= args.max_fit_error_mm else "fail", "reason_code": "ok" if fit_rmse_mm <= args.max_fit_rmse_mm and fit_max_mm <= args.max_fit_error_mm else "fit_residual_above_threshold"}, {"id": "timestamps", "status": "pass" if fit_ok and validation_ok else "fail", "reason_code": "ok" if fit_ok and validation_ok else "timestamp_invalid"}], "blocking_reasons": list(dict.fromkeys(reasons))},
        "input_hashes": [{"path": str(fit["path"]), "sha256": fit["sha256"]}, {"path": str(validation["path"]), "sha256": validation["sha256"]}, {"path": str(quality["path"]), "sha256": quality["sha256"]}],
    }


def invalid_report(reason):
    return {"schema_version": SCHEMA_VERSION, "tool_version": TOOL_VERSION, "generated_at_utc": utc_now(), "candidate_id": None, "candidate_valid": False, "formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False, "quality": {"checks": [{"id": "input", "status": "unknown", "reason_code": reason}], "blocking_reasons": [reason]}, "input_hashes": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a non-promotable offline camera extrinsics candidate")
    parser.add_argument("--fit-samples", required=True, type=Path)
    parser.add_argument("--validation-samples", required=True, type=Path)
    parser.add_argument("--b2-quality", required=True, type=Path)
    parser.add_argument("--out", "--output", dest="out", required=True, type=Path)
    parser.add_argument("--reference-time", default=utc_now())
    parser.add_argument("--max-fit-rmse-mm", type=float, default=10.0)
    parser.add_argument("--max-fit-error-mm", type=float, default=20.0)
    parser.add_argument("--max-timestamp-age-s", type=float, default=86400.0)
    args = parser.parse_args(argv)
    if args.out.name in FORMAL_NAMES:
        parser.error("formal camera_to_base output is forbidden")
    if args.out.resolve() in {args.fit_samples.resolve(), args.validation_samples.resolve(), args.b2_quality.resolve()}:
        parser.error("output must not overwrite an input")
    for name in ("max_fit_rmse_mm", "max_fit_error_mm", "max_timestamp_age_s"):
        if not math.isfinite(float(getattr(args, name))) or float(getattr(args, name)) < 0:
            parser.error(name + " must be finite and non-negative")
    try:
        fit = load_dataset(args.fit_samples)
        validation = load_dataset(args.validation_samples)
        quality = load_quality(args.b2_quality)
        report = build_report(fit, validation, quality, args)
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError, np.linalg.LinAlgError) as error:
        report = invalid_report(str(error))
    atomic_write(args.out, report)
    print(json.dumps({"ok": report["candidate_valid"], "out": str(args.out), "candidate_id": report["candidate_id"], "promotion_locked": True, "blocking_reasons": report["quality"]["blocking_reasons"]}, ensure_ascii=False, indent=2))
    return 0 if report["candidate_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
