#!/usr/bin/env python3
"""Offline photo-to-simulation-target pipeline for the graduation project."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError


SCHEMA_VERSION = "b5.vision-offline.v1"
TOOL_VERSION = "b5-vision.1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACUPOINT_TEMPLATE = (
    ("大椎", 0.50, 0.08),
    ("肺俞-L", 0.38, 0.25),
    ("肺俞-R", 0.62, 0.25),
    ("心俞-L", 0.38, 0.42),
    ("心俞-R", 0.62, 0.42),
    ("肾俞-L", 0.36, 0.72),
    ("肾俞-R", 0.64, 0.72),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name}_not_finite")
    return float(value)


def load_inputs(image_path: Path, depth_path: Path, meta_path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if not image_path.is_file():
        raise ValueError("image_missing")
    if not depth_path.is_file():
        raise ValueError("depth_missing")
    if not meta_path.is_file():
        raise ValueError("meta_missing")
    try:
        with Image.open(image_path) as opened:
            image = np.asarray(opened.convert("RGB"))
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("image_invalid") from error
    if image.ndim != 3 or image.shape[2] != 3 or image.shape[0] < 64 or image.shape[1] < 64 or image.shape[0] > 4096 or image.shape[1] > 4096:
        raise ValueError("image_dimensions_invalid")
    try:
        depth = np.load(depth_path, allow_pickle=False)
    except (OSError, ValueError) as error:
        raise ValueError("depth_invalid") from error
    if depth.ndim != 2 or depth.shape != image.shape[:2]:
        raise ValueError("image_depth_dimensions_mismatch")
    if not np.issubdtype(depth.dtype, np.number) or not np.all(np.isfinite(depth)):
        raise ValueError("depth_non_finite")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError("meta_invalid")
    intrinsics = meta.get("intrinsics")
    if not isinstance(intrinsics, dict):
        raise ValueError("intrinsics_missing")
    for name in ("fx", "fy", "ppx", "ppy"):
        finite_number(intrinsics.get(name), f"intrinsics_{name}")
    if float(intrinsics["fx"]) <= 0 or float(intrinsics["fy"]) <= 0:
        raise ValueError("intrinsics_focal_length_invalid")
    scale = finite_number(meta.get("depth_scale_m_per_unit"), "depth_scale")
    if scale <= 0:
        raise ValueError("depth_scale_invalid")
    return image, depth.astype(np.float64), meta


def detect_target_region(image: np.ndarray, depth_m: np.ndarray) -> tuple[dict[str, Any], np.ndarray]:
    height, width = depth_m.shape
    valid = (depth_m >= 0.05) & (depth_m <= 1.5)
    center = valid[height // 4 : height * 3 // 4, width // 4 : width * 3 // 4]
    center_depth = depth_m[height // 4 : height * 3 // 4, width // 4 : width * 3 // 4][center]
    if center_depth.size < max(100, image.shape[0] * image.shape[1] // 100):
        raise ValueError("target_region_depth_insufficient")
    median_depth = float(np.median(center_depth))
    margin = max(0.08, median_depth * 0.25)
    mask = valid & (depth_m >= median_depth - margin) & (depth_m <= median_depth + margin)
    row_counts = mask.sum(axis=1)
    candidate_rows = np.flatnonzero(row_counts >= max(8, int(width * 0.08)))
    if candidate_rows.size < max(20, int(height * 0.20)):
        raise ValueError("target_region_not_found")
    y0, y1 = int(candidate_rows[0]), int(candidate_rows[-1])
    col_counts = mask[y0 : y1 + 1].sum(axis=0)
    candidate_cols = np.flatnonzero(col_counts >= max(8, int((y1 - y0 + 1) * 0.08)))
    if candidate_cols.size < max(20, int(width * 0.15)):
        raise ValueError("target_region_not_found")
    x0, x1 = int(candidate_cols[0]), int(candidate_cols[-1])
    region = mask[y0 : y1 + 1, x0 : x1 + 1]
    coverage = float(region.mean())
    area_ratio = float(region.size / mask.size)
    gray = image.astype(np.float64).mean(axis=2)
    contrast = float(np.std(gray[y0 : y1 + 1, x0 : x1 + 1]) / 64.0)
    confidence = float(np.clip(0.65 * min(1.0, coverage / 0.60) + 0.25 * min(1.0, area_ratio / 0.25) + 0.10 * min(1.0, contrast), 0.0, 1.0))
    return {"bbox_px": [x0, y0, x1, y1], "center_depth_m": median_depth, "depth_coverage": coverage, "area_ratio": area_ratio, "image_contrast_score": min(1.0, contrast), "confidence": confidence}, mask


def camera_point(depth_m: np.ndarray, intrinsics: dict[str, Any], pixel: tuple[int, int]) -> tuple[list[float], float, int]:
    x, y = pixel
    height, width = depth_m.shape
    radius = 5
    patch = depth_m[max(0, y - radius) : min(height, y + radius + 1), max(0, x - radius) : min(width, x + radius + 1)]
    values = patch[(patch >= 0.05) & (patch <= 1.5)]
    if values.size < 20:
        raise ValueError("acupoint_depth_insufficient")
    z = float(np.median(values))
    residual = float(np.median(np.abs(values - z)))
    px = (x - float(intrinsics["ppx"])) / float(intrinsics["fx"]) * z
    py = (y - float(intrinsics["ppy"])) / float(intrinsics["fy"]) * z
    support = float(values.size / patch.size)
    return [float(px), float(py), z], support * math.exp(-residual / 0.02), int(values.size)


def load_candidate_extrinsics(path: Path, expected_sha256: str | None) -> tuple[dict[str, Any], np.ndarray, np.ndarray, str]:
    if not path.is_file():
        raise ValueError("candidate_extrinsics_missing")
    digest = sha256_file(path)
    if expected_sha256 is None or expected_sha256 != digest:
        raise ValueError("candidate_extrinsics_hash_mismatch")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "b3.camera-extrinsics-candidate.v1" or data.get("candidate_valid") is not True:
        raise ValueError("candidate_extrinsics_invalid")
    if data.get("formal_use_allowed") is not False or data.get("promotion_locked") is not True or data.get("execution_allowed") is not False:
        raise ValueError("candidate_extrinsics_lock_invalid")
    matrix = data.get("matrix")
    if not isinstance(matrix, dict):
        raise ValueError("candidate_extrinsics_matrix_missing")
    rotation = np.asarray(matrix.get("rotation"), dtype=float)
    translation = np.asarray(matrix.get("translation_m"), dtype=float)
    if rotation.shape != (3, 3) or translation.shape != (3,) or not np.all(np.isfinite(rotation)) or not np.all(np.isfinite(translation)):
        raise ValueError("candidate_extrinsics_matrix_invalid")
    if abs(float(np.linalg.det(rotation)) - 1.0) > 1e-5 or float(np.linalg.norm(rotation.T @ rotation - np.eye(3), ord="fro")) > 1e-5:
        raise ValueError("candidate_extrinsics_not_rigid")
    return data, rotation, translation, digest


def build_pipeline(image_path: Path, depth_path: Path, meta_path: Path, candidate_path: Path, expected_hash: str | None, formal_path: Path, min_confidence: float) -> dict[str, Any]:
    image, raw_depth, meta = load_inputs(image_path, depth_path, meta_path)
    scale = float(meta["depth_scale_m_per_unit"])
    depth_m = raw_depth * scale
    region, _ = detect_target_region(image, depth_m)
    candidate, rotation, translation, candidate_hash = load_candidate_extrinsics(candidate_path, expected_hash)
    x0, y0, x1, y1 = region["bbox_px"]
    intrinsics = meta["intrinsics"]
    acupoints = []
    reasons = []
    for name, u, v in ACUPOINT_TEMPLATE:
        x = int(round(x0 + u * (x1 - x0)))
        y = int(round(y0 + v * (y1 - y0)))
        try:
            point_camera, depth_confidence, depth_samples = camera_point(depth_m, intrinsics, (x, y))
            confidence = float(np.clip(region["confidence"] * depth_confidence, 0.0, 1.0))
            point_robot = rotation @ np.asarray(point_camera) + translation
            point_valid = confidence >= min_confidence
            if not point_valid:
                reasons.append(f"low_confidence:{name}")
            simulation_target = {"target_kind": "offline_simulation_only", "coordinate_frame": "robot_base_candidate", "position_m": [float(value) for value in point_robot], "source_acupoint": name, "executable": False} if point_valid else None
            acupoints.append({"name": name, "pixel": [x, y], "point_camera_m": point_camera, "point_robot_candidate_m": [float(value) for value in point_robot], "coordinate_confidence": confidence, "valid_depth_samples": depth_samples, "valid": point_valid, "simulation_endpoint_target": simulation_target})
        except ValueError as error:
            reasons.append(f"{error}:{name}")
            acupoints.append({"name": name, "pixel": [x, y], "coordinate_confidence": 0.0, "valid": False, "blocking_reason": str(error), "simulation_endpoint_target": None})
    if region["confidence"] < min_confidence:
        reasons.append("target_region_confidence_below_minimum")
    formal_exists = formal_path.is_file()
    formal_blocking = [] if formal_exists else ["formal_extrinsics_missing"]
    pipeline_valid = not reasons and len(acupoints) == len(ACUPOINT_TEMPLATE)
    input_hashes = {"image_sha256": sha256_file(image_path), "depth_sha256": sha256_file(depth_path), "meta_sha256": sha256_file(meta_path), "candidate_extrinsics_sha256": candidate_hash}
    identity = {"schema_version": SCHEMA_VERSION, "tool_version": TOOL_VERSION, "input_hashes": input_hashes, "candidate_id": candidate.get("candidate_id"), "minimum_confidence": min_confidence, "acupoints": [{"name": item["name"], "pixel": item["pixel"], "point_robot_candidate_m": item.get("point_robot_candidate_m"), "coordinate_confidence": item["coordinate_confidence"]} for item in acupoints]}
    return {"schema_version": SCHEMA_VERSION, "tool_version": TOOL_VERSION, "generated_at_utc": utc_now(), "pipeline_id": "vision-" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:24], "pipeline_valid": pipeline_valid, "offline_simulation_valid": pipeline_valid, "formal_transform_valid": False, "formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False, "hardware_access": {"d405_accessed": False, "camera_device_opened": False, "nano_accessed": False, "serial_accessed": False, "motor_command_generated": False}, "input": {"image_path": str(image_path), "depth_path": str(depth_path), "meta_path": str(meta_path), **input_hashes}, "target_region": region, "coordinate_frames": {"image": "rgb_pixel", "camera": "d405_camera_offline", "robot": "robot_base_candidate"}, "candidate_extrinsics": {"path": str(candidate_path), "sha256": candidate_hash, "candidate_id": candidate.get("candidate_id"), "formal_use_allowed": False, "promotion_locked": True}, "formal_extrinsics": {"path": str(formal_path), "exists": formal_exists, "used": False}, "thresholds": {"minimum_coordinate_confidence": min_confidence}, "acupoint_count": len(acupoints), "acupoints": acupoints, "blocking_reasons": list(dict.fromkeys(reasons)), "formal_blocking_reasons": formal_blocking, "safety_note": "Targets are offline simulation data, not motor commands."}


def failure_report(reason: str, paths: dict[str, Path]) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "tool_version": TOOL_VERSION, "generated_at_utc": utc_now(), "pipeline_id": None, "pipeline_valid": False, "offline_simulation_valid": False, "formal_transform_valid": False, "formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False, "hardware_access": {"d405_accessed": False, "camera_device_opened": False, "nano_accessed": False, "serial_accessed": False, "motor_command_generated": False}, "input": {name: str(path) for name, path in paths.items()}, "target_region": None, "acupoint_count": 0, "acupoints": [], "blocking_reasons": [reason], "formal_blocking_reasons": ["formal_extrinsics_unavailable"], "safety_note": "No executable target or motor command was generated."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert an offline RGB-D photo into locked simulation endpoint targets")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--depth", required=True, type=Path)
    parser.add_argument("--meta", required=True, type=Path)
    parser.add_argument("--candidate-extrinsics", required=True, type=Path)
    parser.add_argument("--expected-extrinsics-sha256", required=True)
    parser.add_argument("--formal-extrinsics", type=Path, default=PROJECT_ROOT / "calibration" / "camera_to_base.json")
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--out", "--output", dest="out", required=True, type=Path)
    args = parser.parse_args(argv)
    if not math.isfinite(args.min_confidence) or not 0.0 <= args.min_confidence <= 1.0:
        parser.error("min-confidence must be finite and within [0, 1]")
    paths = {"image_path": args.image.resolve(), "depth_path": args.depth.resolve(), "meta_path": args.meta.resolve(), "candidate_extrinsics_path": args.candidate_extrinsics.resolve()}
    if args.out.resolve() in set(paths.values()):
        parser.error("output must not overwrite an input")
    try:
        report = build_pipeline(paths["image_path"], paths["depth_path"], paths["meta_path"], paths["candidate_extrinsics_path"], args.expected_extrinsics_sha256, args.formal_extrinsics.resolve(), args.min_confidence)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        report = failure_report(str(error), paths)
    atomic_write(args.out, report)
    print(json.dumps({"ok": report["pipeline_valid"], "out": str(args.out), "pipeline_id": report["pipeline_id"], "acupoint_count": report["acupoint_count"], "formal_use_allowed": False, "execution_allowed": False, "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False, indent=2))
    return 0 if report["pipeline_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
