#!/usr/bin/env python3
"""Build an offline D405 depth-scale calibration candidate."""

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
FORMAL_OUTPUT_NAME = "d405_depth_calibration.json"
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
        measured = sample.get("measured_z_m", sample.get("camera_z_m"))
        actual = sample.get("actual_z_m", sample.get("actual_distance_m"))
        if measured is None or actual is None:
            raise ValueError(f"sample {index} is missing measured_z_m or actual_z_m")
        measured = float(measured)
        actual = float(actual)
        if not np.isfinite(measured) or not np.isfinite(actual):
            raise ValueError(f"sample {index} contains a non-finite value")
        if measured <= 0 or actual <= 0:
            raise ValueError(f"sample {index} distances must be positive")
        name = str(sample.get("name", f"p{index + 1}"))
        if name in names:
            raise ValueError(f"duplicate sample name: {name}")
        names.add(name)
        clean.append({"name": name, "measured": measured, "actual": actual})

    if len(clean) < 2:
        raise ValueError("at least 2 different distance samples are required")
    if np.ptp([sample["measured"] for sample in clean]) <= 1e-9:
        raise ValueError("measured distances must span more than one value")
    return data, clean


def fit_depth(samples: list[dict]) -> dict:
    measured = np.asarray([sample["measured"] for sample in samples], dtype=float)
    actual = np.asarray([sample["actual"] for sample in samples], dtype=float)
    design = np.vstack([measured, np.ones_like(measured)]).T
    scale, offset = np.linalg.lstsq(design, actual, rcond=None)[0]
    predicted = scale * measured + offset
    errors = predicted - actual
    return {
        "model": "actual_z_m = measured_z_m * scale + offset_m",
        "scale": float(scale),
        "offset_m": float(offset),
        "rmse_mm": float(np.sqrt(np.mean(errors ** 2)) * 1000.0),
        "max_abs_error_mm": float(np.max(np.abs(errors)) * 1000.0),
        "measured_span_m": float(np.ptp(measured)),
        "samples": [
            {
                "name": sample["name"],
                "measured_z_m": sample["measured"],
                "actual_z_m": sample["actual"],
                "corrected_z_m": float(predicted_value),
                "error_mm": float(error * 1000.0),
            }
            for sample, predicted_value, error in zip(samples, predicted, errors)
        ],
    }


def calibration_report(source_path: Path, document: dict, samples: list[dict], args) -> dict:
    fit = fit_depth(samples)
    dataset_kind = str(document.get("dataset_kind", "unspecified"))
    checks = {
        "dataset_is_measurement_candidate": dataset_kind == "measurement_candidate",
        "sample_count": len(samples) >= args.min_samples,
        "distance_span": fit["measured_span_m"] >= args.min_span_m,
        "scale_range": args.min_scale <= fit["scale"] <= args.max_scale,
        "offset_range": abs(fit["offset_m"]) <= args.max_abs_offset_m,
        "rmse": fit["rmse_mm"] <= args.max_rmse_mm,
        "max_error": fit["max_abs_error_mm"] <= args.max_error_mm,
    }
    blocking_reasons = [name for name, passed in checks.items() if not passed]
    calibration_valid = not blocking_reasons
    return {
        "type": "d405_depth_z_calibration",
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "calibrate_d405_depth.py", "version": TOOL_VERSION},
        "generated_at_utc": utc_now(),
        "dataset_kind": dataset_kind,
        "calibration_valid": calibration_valid,
        "formal_use_allowed": False,
        "execution_allowed": False,
        "source": {"path": str(source_path), "sha256": sha256_file(source_path)},
        "coordinate_frame": "d405_camera",
        "units": {"distance": "m", "residual": "mm"},
        "sample_count": len(samples),
        **fit,
        "quality": {
            "thresholds": {
                "min_samples": args.min_samples,
                "min_span_m": args.min_span_m,
                "min_scale": args.min_scale,
                "max_scale": args.max_scale,
                "max_abs_offset_m": args.max_abs_offset_m,
                "max_rmse_mm": args.max_rmse_mm,
                "max_error_mm": args.max_error_mm,
            },
            "checks": checks,
            "blocking_reasons": blocking_reasons,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an offline D405 depth calibration candidate")
    parser.add_argument("--samples", type=Path, default=PROJECT_ROOT / "calibration/d405_depth_samples.json")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "calibration/d405_depth_calibration.candidate.json")
    parser.add_argument("--min-samples", type=int, default=4)
    parser.add_argument("--min-span-m", type=float, default=0.10)
    parser.add_argument("--min-scale", type=float, default=0.90)
    parser.add_argument("--max-scale", type=float, default=1.10)
    parser.add_argument("--max-abs-offset-m", type=float, default=0.05)
    parser.add_argument("--max-rmse-mm", type=float, default=2.0)
    parser.add_argument("--max-error-mm", type=float, default=5.0)
    args = parser.parse_args()

    if args.out.name == FORMAL_OUTPUT_NAME:
        raise SystemExit("B1-C refuses to create d405_depth_calibration.json; use a .candidate.json output")
    if args.min_samples < 2 or args.min_span_m <= 0:
        raise SystemExit("min-samples must be >= 2 and min-span-m must be positive")

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
                "sample_count": report["sample_count"],
                "scale": report["scale"],
                "offset_m": report["offset_m"],
                "rmse_mm": report["rmse_mm"],
                "max_abs_error_mm": report["max_abs_error_mm"],
                "blocking_reasons": report["quality"]["blocking_reasons"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["calibration_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
