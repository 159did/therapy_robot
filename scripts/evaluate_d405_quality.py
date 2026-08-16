#!/usr/bin/env python3
"""Evaluate offline D405 quality facts without connecting to a camera or robot."""

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


TOOL_VERSION = "b2-c.1"
SCHEMA_VERSION = "b2.vision-quality.v1"
DEFAULTS = {
    "min_depth_valid_ratio": 0.85,
    "max_plane_rmse_m": 0.010,
    "max_repeatability_rmse_m": 0.005,
    "min_sample_count": 2,
    "max_timestamp_age_s": 86400.0,
    "max_future_skew_s": 0.0,
}


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


def finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("non_finite_" + name)
    return float(value)


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


def rmse(values):
    values = [finite_number(value, "residual") for value in values]
    if not values:
        raise ValueError("empty_residuals")
    return math.sqrt(sum(value * value for value in values) / len(values))


def vector3(value, name="point"):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("invalid_" + name)
    return tuple(finite_number(item, name) for item in value)


def first(mapping, keys, default=None):
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def normalize_frame(raw, index):
    if not isinstance(raw, dict):
        raise ValueError("frame_schema_invalid")
    quality = raw.get("quality") if isinstance(raw.get("quality"), dict) else {}
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    depth = first(raw, ("depth_valid_ratio", "valid_depth_ratio"), first(metrics, ("depth_valid_ratio",), first(quality, ("valid_depth_ratio",))))
    plane = first(raw, ("plane_rmse_m",), first(metrics, ("plane_rmse_m",), first(quality, ("plane_rmse_m",))))
    if plane is None and "plane_rmse_mm" in raw:
        plane = finite_number(raw["plane_rmse_mm"], "plane_rmse_mm") / 1000.0
    if plane is None and "plane_residuals_m" in raw:
        plane = rmse(raw["plane_residuals_m"])
    if plane is None and "plane_residuals_mm" in raw:
        plane = rmse(raw["plane_residuals_mm"]) / 1000.0
    timestamp = first(raw, ("timestamp_utc", "captured_at_utc", "timestamp"), first(quality, ("timestamp_utc",)))
    if timestamp is None:
        timestamp = raw.get("generated_at_utc")
    point = first(raw, ("point_camera_m", "measurement_m", "point_m"))
    if point is None and isinstance(raw.get("estimate"), dict):
        point = first(raw["estimate"], ("point_camera_m", "point_m"))
    frame = {"frame_id": str(first(raw, ("frame_id", "id", "name"), "frame-" + str(index + 1))), "raw": raw}
    if depth is not None:
        frame["depth_valid_ratio"] = finite_number(depth, "depth_valid_ratio")
        if not 0.0 <= frame["depth_valid_ratio"] <= 1.0:
            raise ValueError("depth_valid_ratio_out_of_range")
    if plane is not None:
        frame["plane_rmse_m"] = finite_number(plane, "plane_rmse_m")
        if frame["plane_rmse_m"] < 0.0:
            raise ValueError("plane_rmse_negative")
    if timestamp is not None:
        frame["timestamp_utc"] = timestamp
    if point is not None:
        frame["point_camera_m"] = vector3(point)
    return frame


def collect_input(path):
    path = Path(path).resolve()
    files = []
    if path.is_dir():
        candidates = [path / "quality_input.json", path / "analysis_result.json", path / "derived" / "analysis-b1c" / "analysis_result.json"]
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            raise ValueError("input_json_missing")
        data = json.loads(source.read_text(encoding="utf-8"))
        files = [candidate for candidate in sorted(path.rglob("*")) if candidate.is_file() and "derived" not in candidate.parts]
    elif path.is_file():
        source = path
        data = json.loads(path.read_text(encoding="utf-8"))
        files = [path]
    else:
        raise ValueError("input_path_missing")
    if not isinstance(data, dict):
        raise ValueError("input_root_invalid")
    raw_frames = data.get("frames", data.get("samples"))
    if raw_frames is None:
        raw_frames = [data]
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ValueError("frames_missing")
    frames = []
    for index, item in enumerate(raw_frames):
        if isinstance(item, dict) and first(item, ("analysis_path", "result_path")):
            ref = Path(first(item, ("analysis_path", "result_path")))
            if not ref.is_absolute():
                ref = source.parent / ref
            if not ref.is_file():
                raise ValueError("frame_input_missing")
            referenced = json.loads(ref.read_text(encoding="utf-8"))
            merged = dict(referenced) if isinstance(referenced, dict) else {}
            merged.update({key: value for key, value in item.items() if key not in ("analysis_path", "result_path")})
            item = merged
            files.append(ref)
        frames.append(normalize_frame(item, index))
    hashes = []
    seen = set()
    for file_path in files:
        file_path = Path(file_path).resolve()
        if file_path in seen or not file_path.is_file():
            continue
        seen.add(file_path)
        hashes.append({"path": str(file_path), "sha256": sha256_file(file_path), "size_bytes": file_path.stat().st_size})
    return data, frames, hashes


def check(check_id, status, value, threshold, reason_code):
    result = {"id": check_id, "status": status, "value": value, "threshold": threshold, "reason_code": reason_code}
    return result


def evaluate(data, frames, args):
    thresholds = {
        "min_depth_valid_ratio": args.min_depth_valid_ratio,
        "max_plane_rmse_m": args.max_plane_rmse_m,
        "max_repeatability_rmse_m": args.max_repeatability_rmse_m,
        "min_sample_count": args.min_sample_count,
        "max_timestamp_age_s": args.max_timestamp_age_s,
        "max_future_skew_s": args.max_future_skew_s,
    }
    reference = parse_timestamp(args.reference_time)
    reasons = []
    depth_values = [frame.get("depth_valid_ratio") for frame in frames]
    plane_values = [frame.get("plane_rmse_m") for frame in frames]
    depth_value = min(depth_values) if all(value is not None for value in depth_values) else None
    plane_value = max(plane_values) if all(value is not None for value in plane_values) else None
    depth_check = check("depth_valid_ratio", "pass", depth_value, args.min_depth_valid_ratio, "ok")
    if depth_value is None:
        depth_check.update(status="unknown", reason_code="depth_valid_ratio_missing"); reasons.append("depth_valid_ratio_missing")
    elif depth_value < args.min_depth_valid_ratio:
        depth_check.update(status="fail", reason_code="depth_valid_ratio_below_minimum"); reasons.append("depth_valid_ratio_below_minimum")
    plane_check = check("plane_rmse", "pass", plane_value, args.max_plane_rmse_m, "ok")
    if plane_value is None:
        plane_check.update(status="unknown", reason_code="plane_rmse_missing"); reasons.append("plane_rmse_missing")
    elif plane_value > args.max_plane_rmse_m:
        plane_check.update(status="fail", reason_code="plane_rmse_above_maximum"); reasons.append("plane_rmse_above_maximum")
    sample_check = check("sample_count", "pass", len(frames), args.min_sample_count, "ok")
    if len(frames) < args.min_sample_count:
        sample_check.update(status="fail", reason_code="sample_count_below_minimum"); reasons.append("sample_count_below_minimum")
    points = [frame.get("point_camera_m") for frame in frames]
    direct_repeat = first(data, ("repeatability_rmse_m",), first(data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}, ("repeatability_rmse_m",)))
    repeatability = finite_number(direct_repeat, "repeatability_rmse_m") if direct_repeat is not None else None
    if repeatability is not None and repeatability < 0.0:
        raise ValueError("repeatability_rmse_negative")
    if repeatability is None and all(point is not None for point in points) and len(points) >= 2:
        center = tuple(sum(point[axis] for point in points) / len(points) for axis in range(3))
        repeatability = math.sqrt(sum(sum((point[axis] - center[axis]) ** 2 for axis in range(3)) for point in points) / len(points))
    repeat_check = check("repeatability_rmse", "pass", repeatability, args.max_repeatability_rmse_m, "ok")
    if len(frames) < args.min_sample_count:
        repeat_check.update(status="fail", reason_code="sample_count_below_minimum")
    elif repeatability is None:
        repeat_check.update(status="unknown", reason_code="repeatability_missing"); reasons.append("repeatability_missing")
    elif repeatability > args.max_repeatability_rmse_m:
        repeat_check.update(status="fail", reason_code="repeatability_above_maximum"); reasons.append("repeatability_above_maximum")
    timestamps = []
    timestamp_error = None
    for frame in frames:
        try:
            timestamps.append(parse_timestamp(frame["timestamp_utc"]))
        except (KeyError, ValueError) as error:
            timestamp_error = str(error); break
    ages = [(reference - timestamp).total_seconds() for timestamp in timestamps] if timestamp_error is None else []
    timestamp_age = max(ages) if ages else None
    timestamp_check = check("timestamp_freshness", "pass", timestamp_age, args.max_timestamp_age_s, "ok")
    if timestamp_error is not None:
        timestamp_check.update(status="unknown", reason_code=timestamp_error); reasons.append(timestamp_error)
    elif any(age > args.max_timestamp_age_s for age in ages):
        timestamp_check.update(status="fail", reason_code="timestamp_too_old"); reasons.append("timestamp_too_old")
    elif any(age < -args.max_future_skew_s for age in ages):
        timestamp_check.update(status="fail", reason_code="timestamp_in_future"); reasons.append("timestamp_in_future")
    order_check = check("timestamp_order", "pass", True, "nondecreasing", "ok")
    if timestamp_error is not None:
        order_check.update(status="unknown", value=None, reason_code="timestamp_missing"); reasons.append("timestamp_missing")
    elif any(right < left for left, right in zip(timestamps, timestamps[1:])):
        order_check.update(status="fail", value=False, reason_code="timestamp_order_invalid"); reasons.append("timestamp_order_invalid")
    checks = [sample_check, depth_check, plane_check, repeat_check, timestamp_check, order_check]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "quality_valid": not reasons and all(item["status"] == "pass" for item in checks),
        "formal_use_allowed": False,
        "execution_allowed": False,
        "sample_count": len(frames),
        "metrics": {"depth_valid_ratio": depth_value, "plane_rmse_m": plane_value, "repeatability_rmse_m": repeatability, "timestamp_age_s": timestamp_age},
        "thresholds": thresholds,
        "checks": checks,
        "blocking_reasons": list(dict.fromkeys(reasons)),
        "reference_time_utc": args.reference_time,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate an offline D405 quality fixture")
    parser.add_argument("input_path", type=Path, nargs="?")
    parser.add_argument("--input", dest="input_option", type=Path, default=None)
    parser.add_argument("--out", "--output", dest="out", type=Path, default=None)
    parser.add_argument("--reference-time", default=utc_now())
    parser.add_argument("--min-depth-valid-ratio", "--min-valid-depth-ratio", dest="min_depth_valid_ratio", type=float, default=DEFAULTS["min_depth_valid_ratio"])
    parser.add_argument("--max-plane-rmse-m", "--max-plane-residual-m", dest="max_plane_rmse_m", type=float, default=DEFAULTS["max_plane_rmse_m"])
    parser.add_argument("--max-repeatability-rmse-m", dest="max_repeatability_rmse_m", type=float, default=DEFAULTS["max_repeatability_rmse_m"])
    parser.add_argument("--min-sample-count", type=int, default=DEFAULTS["min_sample_count"])
    parser.add_argument("--max-timestamp-age-s", type=float, default=DEFAULTS["max_timestamp_age_s"])
    parser.add_argument("--max-future-skew-s", type=float, default=DEFAULTS["max_future_skew_s"])
    args = parser.parse_args(argv)
    args.input = args.input_option or args.input_path
    if args.input is None:
        parser.error("an input path is required")
    for name in ("min_depth_valid_ratio", "max_plane_rmse_m", "max_repeatability_rmse_m", "max_timestamp_age_s", "max_future_skew_s"):
        value = getattr(args, name)
        if not math.isfinite(float(value)) or float(value) < 0.0:
            parser.error(name + " must be finite and non-negative")
    if args.min_depth_valid_ratio > 1.0:
        parser.error("min_depth_valid_ratio must be at most 1")
    if args.min_sample_count < 1:
        parser.error("min_sample_count must be positive")
    out = args.out or (args.input / "derived" / "quality-b2" / "quality_result.json" if args.input.is_dir() else args.input.with_name("quality_result.json"))
    result = {"schema_version": SCHEMA_VERSION, "tool_version": TOOL_VERSION, "quality_valid": False, "formal_use_allowed": False, "execution_allowed": False, "sample_count": 0, "metrics": {"depth_valid_ratio": None, "plane_rmse_m": None, "repeatability_rmse_m": None, "timestamp_age_s": None}, "thresholds": {"min_depth_valid_ratio": args.min_depth_valid_ratio, "max_plane_rmse_m": args.max_plane_rmse_m, "max_repeatability_rmse_m": args.max_repeatability_rmse_m, "min_sample_count": args.min_sample_count, "max_timestamp_age_s": args.max_timestamp_age_s, "max_future_skew_s": args.max_future_skew_s}, "checks": [], "blocking_reasons": []}
    try:
        data, frames, hashes = collect_input(args.input)
        result.update(evaluate(data, frames, args)); result["input_hashes"] = hashes
    except (OSError, ValueError, json.JSONDecodeError) as error:
        result["blocking_reasons"] = [str(error)]; result["checks"] = [{"id": "input", "status": "unknown", "value": None, "threshold": None, "reason_code": str(error)}]; result["input_hashes"] = []
    result["generated_at_utc"] = utc_now()
    atomic_write(out, result)
    print(json.dumps({"ok": result["quality_valid"], "json": str(out.resolve()), "quality_valid": result["quality_valid"], "blocking_reasons": result["blocking_reasons"]}, ensure_ascii=False, indent=2))
    return 0 if result["quality_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
