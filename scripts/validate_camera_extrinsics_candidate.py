#!/usr/bin/env python3
"""Independently validate a B3-C camera extrinsics candidate offline."""

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


CANDIDATE_SCHEMA = "b3.camera-extrinsics-candidate.v1"
DATASET_SCHEMA = "b3.camera-samples.v1"
VALIDATION_SCHEMA = "b3.camera-extrinsics-validation.v1"
TOOL_VERSION = "b3-c.1"


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
    if not isinstance(data, dict) or data.get("schema_version") != DATASET_SCHEMA or data.get("dataset_kind") != "measurement_candidate":
        raise ValueError("validation_dataset_schema_invalid")
    if data.get("batch_id") in (None, ""):
        raise ValueError("validation_batch_id_missing")
    frames = data.get("coordinate_frames")
    units = data.get("units")
    if not isinstance(frames, dict) or frames.get("source") != "d405_camera" or frames.get("target") != "robot_base":
        raise ValueError("validation_coordinate_frames_invalid")
    if not isinstance(units, dict) or units.get("points") != "m":
        raise ValueError("validation_point_units_invalid")
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("validation_samples_missing")
    clean = []
    ids = set()
    timestamps = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("validation_sample_schema_invalid")
        sample_id = sample.get("sample_id", sample.get("name"))
        if not isinstance(sample_id, str) or not sample_id or sample_id in ids:
            raise ValueError("validation_sample_id_missing_or_duplicate")
        ids.add(sample_id)
        timestamp = sample.get("timestamp_utc", data.get("captured_at_utc"))
        timestamps.append(parse_timestamp(timestamp))
        item = {"sample_id": sample_id, "camera": vector(sample.get("camera_point_m"), "camera_point_m"), "base": vector(sample.get("robot_point_m"), "robot_point_m"), "timestamp_utc": timestamp}
        if "camera_normal" in sample or "robot_normal" in sample:
            if "camera_normal" not in sample or "robot_normal" not in sample:
                raise ValueError("validation_normal_pair_incomplete")
            item["camera_normal"] = vector(sample["camera_normal"], "camera_normal")
            item["robot_normal"] = vector(sample["robot_normal"], "robot_normal")
        clean.append(item)
    if any(right < left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("validation_timestamp_order_invalid")
    return {"path": path, "data": data, "batch_id": data["batch_id"], "samples": clean, "sample_ids": ids, "timestamps": timestamps, "sha256": sha256_file(path)}


def load_quality(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "b2.vision-quality.v1" or data.get("quality_valid") is not True:
        raise ValueError("b2_quality_invalid")
    if data.get("formal_use_allowed") is not False or data.get("execution_allowed") is not False:
        raise ValueError("b2_quality_execution_flags_invalid")
    if data.get("blocking_reasons") or any(isinstance(item, dict) and item.get("status") != "pass" for item in data.get("checks", [])):
        raise ValueError("b2_quality_checks_not_all_pass")
    return {"path": path, "sha256": sha256_file(path), "data": data}


def transform(matrix, sample):
    rotation = matrix["rotation"]
    translation = matrix["translation_m"]
    return rotation @ sample["camera"] + translation


def validate(candidate, validation, quality, args):
    reasons = []
    if candidate.get("schema_version") != CANDIDATE_SCHEMA:
        reasons.append("candidate_schema_invalid")
    if candidate.get("candidate_valid") is not True:
        reasons.append("candidate_not_valid")
    if candidate.get("formal_use_allowed") is not False or candidate.get("promotion_locked") is not True or candidate.get("execution_allowed") is not False:
        reasons.append("candidate_promotion_lock_invalid")
    expected_hash = candidate.get("validation_input", {}).get("sha256")
    if expected_hash != validation["sha256"]:
        reasons.append("validation_input_hash_mismatch")
    if candidate.get("fit_input", {}).get("sha256") == validation["sha256"]:
        reasons.append("input_hash_reused")
    expected_quality_hash = candidate.get("quality_binding", {}).get("sha256")
    if expected_quality_hash != quality["sha256"]:
        reasons.append("b2_quality_hash_mismatch")
    expected_batch = candidate.get("validation_input", {}).get("batch_id")
    if expected_batch != validation["batch_id"]:
        reasons.append("validation_batch_id_mismatch")
    fit_batch = candidate.get("fit_input", {}).get("batch_id")
    if fit_batch == validation["batch_id"]:
        reasons.append("batch_id_reused")
    fit_ids = set(candidate.get("fit_input", {}).get("sample_ids", []))
    if fit_ids & validation["sample_ids"]:
        reasons.append("sample_id_reused")
    matrix_document = candidate.get("matrix")
    if not isinstance(matrix_document, dict):
        raise ValueError("candidate_matrix_missing")
    rotation = np.asarray(matrix_document.get("rotation"), dtype=float)
    translation = vector(matrix_document.get("translation_m"), "translation_m")
    if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
        raise ValueError("candidate_rotation_invalid")
    determinant = float(np.linalg.det(rotation))
    orthonormal_error = float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro"))
    if abs(determinant - 1.0) > 1e-6 or orthonormal_error > 1e-6:
        reasons.append("candidate_rotation_not_rigid")
    ages = [(parse_timestamp(args.reference_time) - timestamp).total_seconds() for timestamp in validation["timestamps"]]
    timestamp_age = max(ages)
    if any(age > args.max_timestamp_age_s for age in ages):
        reasons.append("validation_timestamp_too_old")
    if any(age < 0 for age in ages):
        reasons.append("validation_timestamp_in_future")
    predicted = [rotation @ sample["camera"] + translation for sample in validation["samples"]]
    errors = [float(np.linalg.norm(result - sample["base"])) for result, sample in zip(predicted, validation["samples"])]
    rmse_mm = float(np.sqrt(np.mean(np.asarray(errors) ** 2)) * 1000.0)
    max_error_mm = float(np.max(errors) * 1000.0)
    centroid_error_mm = float(np.linalg.norm(np.mean(np.asarray(predicted), axis=0) - np.mean(np.asarray([sample["base"] for sample in validation["samples"]]), axis=0)) * 1000.0)
    direction_error_deg = None
    direction_available = all("camera_normal" in sample and "robot_normal" in sample for sample in validation["samples"])
    if direction_available:
        angles = []
        for sample in validation["samples"]:
            camera_normal = sample["camera_normal"] / np.linalg.norm(sample["camera_normal"])
            robot_normal = sample["robot_normal"] / np.linalg.norm(sample["robot_normal"])
            transformed_normal = rotation @ camera_normal
            transformed_normal = transformed_normal / np.linalg.norm(transformed_normal)
            angles.append(math.degrees(math.acos(float(np.clip(np.dot(transformed_normal, robot_normal), -1.0, 1.0)))))
        direction_error_deg = float(max(angles))
        if direction_error_deg > args.max_direction_error_deg:
            reasons.append("direction_error_above_maximum")
    if rmse_mm > args.max_rmse_mm:
        reasons.append("validation_rmse_above_maximum")
    if max_error_mm > args.max_error_mm:
        reasons.append("validation_error_above_maximum")
    checks = [
        {"id": "candidate_schema", "status": "pass" if "candidate_schema_invalid" not in reasons else "fail", "value": candidate.get("schema_version"), "threshold": CANDIDATE_SCHEMA, "reason_code": "ok" if "candidate_schema_invalid" not in reasons else "candidate_schema_invalid"},
        {"id": "input_hash_binding", "status": "pass" if "validation_input_hash_mismatch" not in reasons and "b2_quality_hash_mismatch" not in reasons else "fail", "value": True, "threshold": True, "reason_code": "ok" if "validation_input_hash_mismatch" not in reasons and "b2_quality_hash_mismatch" not in reasons else "input_hash_mismatch"},
        {"id": "matrix_rigid", "status": "pass" if "candidate_rotation_not_rigid" not in reasons else "fail", "value": {"determinant": determinant, "orthonormal_error": orthonormal_error}, "threshold": {"determinant": 1.0, "orthonormal_error": 1e-6}, "reason_code": "ok" if "candidate_rotation_not_rigid" not in reasons else "candidate_rotation_not_rigid"},
        {"id": "validation_rmse", "status": "pass" if rmse_mm <= args.max_rmse_mm else "fail", "value": rmse_mm, "threshold": args.max_rmse_mm, "reason_code": "ok" if rmse_mm <= args.max_rmse_mm else "validation_rmse_above_maximum"},
        {"id": "validation_max_error", "status": "pass" if max_error_mm <= args.max_error_mm else "fail", "value": max_error_mm, "threshold": args.max_error_mm, "reason_code": "ok" if max_error_mm <= args.max_error_mm else "validation_error_above_maximum"},
        {"id": "direction_error", "status": "pass" if direction_error_deg is None or direction_error_deg <= args.max_direction_error_deg else "fail", "value": direction_error_deg, "threshold": args.max_direction_error_deg, "reason_code": "not_provided" if direction_error_deg is None else ("ok" if direction_error_deg <= args.max_direction_error_deg else "direction_error_above_maximum")},
        {"id": "timestamp_freshness", "status": "pass" if not any(reason.startswith("validation_timestamp_") for reason in reasons) else "fail", "value": timestamp_age, "threshold": args.max_timestamp_age_s, "reason_code": "ok" if not any(reason.startswith("validation_timestamp_") for reason in reasons) else "timestamp_invalid"},
    ]
    return {
        "schema_version": VALIDATION_SCHEMA,
        "tool_version": TOOL_VERSION,
        "generated_at_utc": utc_now(),
        "candidate_id": candidate.get("candidate_id"),
        "validation_valid": not reasons and all(item["status"] == "pass" for item in checks),
        "formal_use_allowed": False,
        "promotion_locked": True,
        "execution_allowed": False,
        "entity_action_authorized": False,
        "nano_deployment_authorized": False,
        "candidate_input": {"path": str(args.candidate.resolve()), "sha256": sha256_file(args.candidate)},
        "validation_input": {"path": str(validation["path"]), "sha256": validation["sha256"], "batch_id": validation["batch_id"], "sample_count": len(validation["samples"])},
        "quality_binding": {"path": str(quality["path"]), "sha256": quality["sha256"], "quality_valid": True},
        "coordinate_frames": {"source": "d405_camera", "target": "robot_base"},
        "units": {"translation": "m", "residual": "mm", "angle": "deg"},
        "metrics": {"validation_rmse_mm": rmse_mm, "validation_max_error_mm": max_error_mm, "centroid_error_mm": centroid_error_mm, "direction_error_deg": direction_error_deg, "timestamp_age_s": timestamp_age},
        "thresholds": {"max_rmse_mm": args.max_rmse_mm, "max_error_mm": args.max_error_mm, "max_direction_error_deg": args.max_direction_error_deg, "max_timestamp_age_s": args.max_timestamp_age_s},
        "checks": checks,
        "blocking_reasons": list(dict.fromkeys(reasons)),
        "input_hashes": [{"path": str(args.candidate.resolve()), "sha256": sha256_file(args.candidate)}, {"path": str(validation["path"]), "sha256": validation["sha256"]}, {"path": str(quality["path"]), "sha256": quality["sha256"]}],
    }


def invalid_report(reason, candidate_path=None):
    return {"schema_version": VALIDATION_SCHEMA, "tool_version": TOOL_VERSION, "generated_at_utc": utc_now(), "candidate_id": None, "validation_valid": False, "formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False, "candidate_input": {"path": str(candidate_path) if candidate_path else None}, "checks": [{"id": "input", "status": "unknown", "value": None, "threshold": None, "reason_code": reason}], "blocking_reasons": [reason], "input_hashes": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate a B3-C camera extrinsics candidate using an independent dataset")
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--validation-samples", required=True, type=Path)
    parser.add_argument("--b2-quality", required=True, type=Path)
    parser.add_argument("--out", "--output", dest="out", required=True, type=Path)
    parser.add_argument("--reference-time", default=utc_now())
    parser.add_argument("--max-rmse-mm", type=float, default=10.0)
    parser.add_argument("--max-error-mm", type=float, default=20.0)
    parser.add_argument("--max-direction-error-deg", type=float, default=5.0)
    parser.add_argument("--max-timestamp-age-s", type=float, default=86400.0)
    args = parser.parse_args(argv)
    if args.out.name in {"camera_to_base.json", "camera_to_base.candidate.json"}:
        parser.error("formal camera_to_base output is forbidden")
    if args.out.resolve() in {args.candidate.resolve(), args.validation_samples.resolve(), args.b2_quality.resolve()}:
        parser.error("output must not overwrite an input")
    for name in ("max_rmse_mm", "max_error_mm", "max_direction_error_deg", "max_timestamp_age_s"):
        if not math.isfinite(float(getattr(args, name))) or float(getattr(args, name)) < 0:
            parser.error(name + " must be finite and non-negative")
    try:
        candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
        validation = load_dataset(args.validation_samples)
        quality = load_quality(args.b2_quality)
        report = validate(candidate, validation, quality, args)
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError, np.linalg.LinAlgError) as error:
        report = invalid_report(str(error), args.candidate)
    atomic_write(args.out, report)
    print(json.dumps({"ok": report["validation_valid"], "out": str(args.out), "candidate_id": report["candidate_id"], "promotion_locked": True, "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False, indent=2))
    return 0 if report["validation_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
