#!/usr/bin/env python3
"""Transform offline D405 acupoints into the robot base frame."""

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


def failure_report(result_path: Path, extrinsics_path: Path, reason: str) -> dict:
    return {
        "type": "acupoints_in_robot_base",
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "export_acupoints_base.py", "version": TOOL_VERSION},
        "generated_at_utc": utc_now(),
        "calibration_valid": False,
        "quality_valid": False,
        "formal_use_allowed": False,
        "execution_allowed": False,
        "source_result": str(result_path),
        "extrinsics": str(extrinsics_path),
        "count": 0,
        "quality": {"blocking_reasons": [reason]},
        "acupoints": [],
    }


def load_extrinsics(path: Path) -> tuple[dict, np.ndarray, np.ndarray]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") != "camera_to_robot_base_rigid_transform":
        raise ValueError("unexpected extrinsics type")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported extrinsics schema_version")
    if data.get("calibration_valid") is not True:
        raise ValueError("extrinsics calibration_valid is not true")

    rotation = np.asarray(data["rotation"], dtype=float).reshape(3, 3)
    translation = np.asarray(data["translation_m"], dtype=float).reshape(3)
    if not np.all(np.isfinite(rotation)) or not np.all(np.isfinite(translation)):
        raise ValueError("extrinsics contain non-finite values")
    if abs(float(np.linalg.det(rotation)) - 1.0) > 1e-5:
        raise ValueError("extrinsics rotation determinant is invalid")
    if float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro")) > 1e-5:
        raise ValueError("extrinsics rotation is not orthonormal")
    return data, rotation, translation


def transform_points(result_path: Path, extrinsics_path: Path, args) -> dict:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    extrinsics, rotation, translation = load_extrinsics(extrinsics_path)
    if result.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("analysis result is missing supported schema_version")
    if result.get("quality", {}).get("analysis_valid") is not True:
        raise ValueError("analysis result quality.analysis_valid is not true")

    points = result.get("template_acupoints") or result.get("acupoints") or []
    if not isinstance(points, list) or not points:
        raise ValueError("analysis result contains no acupoints")

    out_points = []
    rejected = []
    for index, point in enumerate(points):
        reason = None
        try:
            if not isinstance(point, dict):
                reason = "point_not_object"
            elif point.get("ok") is not True:
                reason = "point_not_ok"
            elif "point_camera_m" not in point or "normal_camera" not in point:
                reason = "missing_camera_geometry"
            elif int(point.get("valid", 0)) < args.min_valid_depth_samples:
                reason = "insufficient_depth_samples"
            elif float(point.get("residual_median_mm", float("inf"))) > args.max_residual_median_mm:
                reason = "depth_residual_too_large"
            else:
                point_camera = np.asarray(point["point_camera_m"], dtype=float).reshape(3)
                normal_camera = np.asarray(point["normal_camera"], dtype=float).reshape(3)
                if not np.all(np.isfinite(point_camera)) or not np.all(np.isfinite(normal_camera)):
                    reason = "non_finite_camera_geometry"
                elif float(np.linalg.norm(normal_camera)) <= 1e-9:
                    reason = "zero_camera_normal"
                else:
                    point_base = rotation @ point_camera + translation
                    normal_base = rotation @ normal_camera
                    normal_base /= np.linalg.norm(normal_base)
                    out_points.append(
                        {
                            "name": point.get("name"),
                            "pixel": point.get("pixel"),
                            "point_camera_m": [float(value) for value in point_camera],
                            "normal_camera": [float(value) for value in normal_camera],
                            "point_base_m": [float(value) for value in point_base],
                            "point_base_mm": [float(value * 1000.0) for value in point_base],
                            "normal_base": [float(value) for value in normal_base],
                            "valid_depth_samples": int(point.get("valid", 0)),
                            "residual_median_mm": float(point.get("residual_median_mm")),
                        }
                    )
        except (TypeError, ValueError, KeyError):
            reason = "invalid_point_geometry"
        if reason is not None:
            rejected.append({"index": index, "name": point.get("name") if isinstance(point, dict) else None, "reason": reason})

    quality_valid = bool(out_points) and not rejected
    blocking_reasons = [] if quality_valid else (["no_valid_points"] if not out_points else [])
    if rejected:
        blocking_reasons.append("point_quality_rejected")
    return {
        "type": "acupoints_in_robot_base",
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "export_acupoints_base.py", "version": TOOL_VERSION},
        "generated_at_utc": utc_now(),
        "calibration_valid": True,
        "quality_valid": quality_valid,
        "formal_use_allowed": False,
        "execution_allowed": False,
        "source": {
            "result_path": str(result_path),
            "result_sha256": sha256_file(result_path),
            "extrinsics_path": str(extrinsics_path),
            "extrinsics_sha256": sha256_file(extrinsics_path),
        },
        "coordinate_frames": {"source": "d405_camera", "target": "robot_base"},
        "units": {"points": "m", "point_display": "mm", "residual": "mm"},
        "extrinsics_rmse_mm": extrinsics.get("rmse_mm"),
        "count": len(out_points),
        "quality": {
            "thresholds": {
                "min_valid_depth_samples": args.min_valid_depth_samples,
                "max_residual_median_mm": args.max_residual_median_mm,
            },
            "rejected_points": rejected,
            "blocking_reasons": blocking_reasons,
        },
        "usage": "point_base_m is for offline visualization only; execution_allowed remains false",
        "acupoints": out_points,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Transform offline D405 acupoints to robot-base coordinates")
    parser.add_argument("--result", type=Path, default=PROJECT_ROOT / "data/d405_samples/back_20260617_212933_470/analysis_result.json")
    parser.add_argument("--extrinsics", type=Path, default=PROJECT_ROOT / "calibration/camera_to_base.json")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data/d405_samples/acupoints_base.candidate.json")
    parser.add_argument("--min-valid-depth-samples", type=int, default=100)
    parser.add_argument("--max-residual-median-mm", type=float, default=10.0)
    args = parser.parse_args()

    result_path = args.result.resolve()
    extrinsics_path = args.extrinsics.resolve()
    try:
        if not result_path.exists():
            raise ValueError(f"analysis result does not exist: {result_path}")
        if not extrinsics_path.exists():
            raise ValueError(f"extrinsics file does not exist: {extrinsics_path}")
        output = transform_points(result_path, extrinsics_path, args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        output = failure_report(result_path, extrinsics_path, str(error))

    write_json_atomic(args.out, output)
    print(json.dumps({
        "ok": output.get("calibration_valid") is True and output.get("quality_valid") is True,
        "out": str(args.out),
        "calibration_valid": output.get("calibration_valid", False),
        "quality_valid": output.get("quality_valid", False),
        "execution_allowed": False,
        "count": output.get("count", 0),
        "blocking_reasons": output.get("quality", {}).get("blocking_reasons", []),
    }, ensure_ascii=False, indent=2))
    return 0 if output.get("calibration_valid") is True and output.get("quality_valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
