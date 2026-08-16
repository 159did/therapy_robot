#!/usr/bin/env python3
"""Build an offline D405-camera to robot-base calibration candidate."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile

import numpy as np


SCHEMA_VERSION = 1
TOOL_VERSION = "b1-c.1"
FORMAL_OUTPUT_NAME = "camera_to_base.json"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_samples(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("sample document must be a JSON object")
    samples = data.get("samples", [])
    if not isinstance(samples, list):
        raise ValueError("samples must be a JSON array")

    clean = []
    names = set()
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"sample {index} must be an object")
        camera = sample.get("camera_point_m") or sample.get("camera_m") or sample.get("camera")
        base = sample.get("robot_point_m") or sample.get("base_point_m") or sample.get("robot_m") or sample.get("base")
        if camera is None or base is None:
            raise ValueError(f"sample {index} is missing camera_point_m or robot_point_m")
        camera = np.asarray(camera, dtype=float).reshape(3)
        base = np.asarray(base, dtype=float).reshape(3)
        if not np.all(np.isfinite(camera)) or not np.all(np.isfinite(base)):
            raise ValueError(f"sample {index} contains a non-finite coordinate")
        name = str(sample.get("name", f"p{index + 1}"))
        if name in names:
            raise ValueError(f"duplicate sample name: {name}")
        names.add(name)
        clean.append({"name": name, "camera": camera, "base": base})

    if len(clean) < 3:
        raise ValueError("at least 3 non-collinear point pairs are required")
    return data, clean


def solve_rigid_transform(camera_points, base_points):
    camera = np.asarray(camera_points, dtype=float)
    base = np.asarray(base_points, dtype=float)
    camera_mean = camera.mean(axis=0)
    base_mean = base.mean(axis=0)
    camera_centered = camera - camera_mean
    base_centered = base - base_mean
    u, _, vt = np.linalg.svd(camera_centered.T @ base_centered)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    translation = base_mean - rotation @ camera_mean
    predicted = (rotation @ camera.T).T + translation
    errors = np.linalg.norm(predicted - base, axis=1)
    return rotation, translation, predicted, errors


def condition_report(points) -> dict:
    points = np.asarray(points, dtype=float)
    _, singular_values, _ = np.linalg.svd(points - points.mean(axis=0), full_matrices=False)
    rank = int(np.sum(singular_values > max(1e-9, singular_values[0] * 1e-4))) if singular_values.size else 0
    return {
        "rank": rank,
        "singular_values": [float(value) for value in singular_values],
    }


def calibration_report(source_path: Path, document: dict, samples: list[dict], args) -> dict:
    camera = np.asarray([sample["camera"] for sample in samples], dtype=float)
    base = np.asarray([sample["base"] for sample in samples], dtype=float)
    condition = condition_report(camera)
    rotation, translation, predicted, errors = solve_rigid_transform(camera, base)
    rmse_mm = float(np.sqrt(np.mean(errors ** 2)) * 1000.0)
    max_error_mm = float(np.max(errors) * 1000.0)
    determinant = float(np.linalg.det(rotation))
    orthonormal_error = float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro"))
    dataset_kind = str(document.get("dataset_kind", "unspecified"))

    checks = {
        "dataset_is_measurement_candidate": dataset_kind == "measurement_candidate",
        "point_count": len(samples) >= args.min_points,
        "camera_point_rank": condition["rank"] >= args.min_rank,
        "rmse": rmse_mm <= args.max_rmse_mm,
        "max_error": max_error_mm <= args.max_error_mm,
        "rotation_determinant": abs(determinant - 1.0) <= 1e-6,
        "rotation_orthonormal": orthonormal_error <= 1e-6,
    }
    blocking_reasons = [name for name, passed in checks.items() if not passed]
    calibration_valid = not blocking_reasons

    result_samples = []
    for sample, point, error in zip(samples, predicted, errors):
        result_samples.append(
            {
                "name": sample["name"],
                "camera_point_m": [float(value) for value in sample["camera"]],
                "robot_point_m": [float(value) for value in sample["base"]],
                "pred_robot_point_m": [float(value) for value in point],
                "error_mm": float(error * 1000.0),
            }
        )

    return {
        "type": "camera_to_robot_base_rigid_transform",
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "calibrate_camera_to_base.py", "version": TOOL_VERSION},
        "generated_at_utc": utc_now(),
        "dataset_kind": dataset_kind,
        "calibration_valid": calibration_valid,
        "formal_use_allowed": False,
        "execution_allowed": False,
        "source": {"path": str(source_path), "sha256": sha256_file(source_path)},
        "coordinate_frames": {"source": "d405_camera", "target": "robot_base"},
        "units": {"points": "m", "translation": "m", "residual": "mm"},
        "point_count": len(samples),
        "rotation": [[float(value) for value in row] for row in rotation],
        "translation_m": [float(value) for value in translation],
        "rmse_mm": rmse_mm,
        "max_error_mm": max_error_mm,
        "rotation_determinant": determinant,
        "rotation_orthonormal_error": orthonormal_error,
        "camera_point_condition": condition,
        "quality": {
            "thresholds": {
                "min_points": args.min_points,
                "min_rank": args.min_rank,
                "max_rmse_mm": args.max_rmse_mm,
                "max_error_mm": args.max_error_mm,
            },
            "checks": checks,
            "blocking_reasons": blocking_reasons,
        },
        "usage": "p_base = R @ p_camera + t; normal_base = R @ normal_camera",
        "samples": result_samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an offline D405-to-base calibration candidate")
    parser.add_argument("--samples", type=Path, default=PROJECT_ROOT / "calibration/camera_to_base_samples.json")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "calibration/camera_to_base.candidate.json")
    parser.add_argument("--min-points", type=int, default=9)
    parser.add_argument("--min-rank", type=int, default=2)
    parser.add_argument("--max-rmse-mm", "--min-rmse-mm", dest="max_rmse_mm", type=float, default=10.0)
    parser.add_argument("--max-error-mm", type=float, default=20.0)
    args = parser.parse_args()

    if args.out.name == FORMAL_OUTPUT_NAME:
        raise SystemExit("B1-C refuses to create camera_to_base.json; use a .candidate.json output")
    if args.min_points < 3 or args.min_rank < 2:
        raise SystemExit("min-points must be >= 3 and min-rank must be >= 2")

    source_path = args.samples.resolve()
    document, samples = load_samples(source_path)
    report = calibration_report(source_path, document, samples, args)
    write_json_atomic(args.out, report)
    print(
        json.dumps(
            {
                "ok": report["calibration_valid"],
                "out": str(args.out),
                "calibration_valid": report["calibration_valid"],
                "formal_use_allowed": False,
                "point_count": report["point_count"],
                "rmse_mm": report["rmse_mm"],
                "max_error_mm": report["max_error_mm"],
                "blocking_reasons": report["quality"]["blocking_reasons"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["calibration_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
