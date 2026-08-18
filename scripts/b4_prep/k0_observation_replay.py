#!/usr/bin/env python3
"""Validate and replay synthetic K0 observation records without hardware access."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import sys
from pathlib import Path
from typing import Any


INPUT_SCHEMA_VERSION = "b4.k0-observation.v1"
REPORT_SCHEMA_VERSION = "b4.k0-observation-report.v1"
ROOT_KEYS = {"schema_version", "synthetic", "source", "safety", "limits", "samples", "integrity"}
SOURCE_KEYS = {"kind", "session_id", "device_id", "generated_at_utc"}
SAFETY_KEYS = {
    "formal_use_allowed",
    "execution_allowed",
    "entity_action_authorized",
    "nano_deployment_authorized",
    "h1_window_authorized",
}
LIMIT_KEYS = {
    "height_unit",
    "velocity_unit",
    "time_unit",
    "lower",
    "upper",
    "max_feedback_age_ms",
    "max_sample_gap_ms",
}
SAMPLE_KEYS = {
    "sequence",
    "monotonic_ms",
    "height",
    "velocity",
    "brake_state",
    "feedback_quality",
    "feedback_age_ms",
    "stop_state",
}
INTEGRITY_KEYS = {"algorithm", "payload_sha256"}
LOCKED_SAFETY = {key: False for key in sorted(SAFETY_KEYS)}


class ObservationError(ValueError):
    """Raised when an observation cannot be trusted for offline analysis."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ObservationError(f"document: duplicate key '{key}'")
        result[key] = value
    return result


def payload_digest(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "integrity"}
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _require_exact_keys(value: Any, expected: set[str], location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ObservationError(f"{location}: expected object")
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise ObservationError(f"{location}: {'; '.join(details)}")
    return value


def _require_bool(value: Any, location: str) -> bool:
    if type(value) is not bool:
        raise ObservationError(f"{location}: expected boolean")
    return value


def _require_int(value: Any, location: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ObservationError(f"{location}: expected integer >= {minimum}")
    return value


def _require_number(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObservationError(f"{location}: expected number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ObservationError(f"{location}: expected finite number")
    return converted


def _require_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ObservationError(f"{location}: expected non-empty string")
    return value


def _validate_envelope(document: Any) -> dict[str, Any]:
    root = _require_exact_keys(document, ROOT_KEYS, "document")
    if root["schema_version"] != INPUT_SCHEMA_VERSION:
        raise ObservationError("schema_version: unsupported value")
    if _require_bool(root["synthetic"], "synthetic") is not True:
        raise ObservationError("synthetic: only synthetic offline records are accepted")

    source = _require_exact_keys(root["source"], SOURCE_KEYS, "source")
    if source["kind"] != "synthetic_fixture":
        raise ObservationError("source.kind: only synthetic_fixture is accepted")
    _require_string(source["session_id"], "source.session_id")
    if source["device_id"] != "none":
        raise ObservationError("source.device_id: must be 'none' for offline replay")
    generated_at = _require_string(source["generated_at_utc"], "source.generated_at_utc")
    if not generated_at.endswith("Z"):
        raise ObservationError("source.generated_at_utc: expected UTC value ending in Z")

    safety = _require_exact_keys(root["safety"], SAFETY_KEYS, "safety")
    for key in SAFETY_KEYS:
        if _require_bool(safety[key], f"safety.{key}") is not False:
            raise ObservationError(f"safety.{key}: must remain false")

    integrity = _require_exact_keys(root["integrity"], INTEGRITY_KEYS, "integrity")
    if integrity["algorithm"] != "sha256":
        raise ObservationError("integrity.algorithm: only sha256 is supported")
    declared_digest = _require_string(integrity["payload_sha256"], "integrity.payload_sha256")
    if len(declared_digest) != 64 or any(char not in "0123456789abcdef" for char in declared_digest):
        raise ObservationError("integrity.payload_sha256: expected lowercase SHA-256 hex")
    try:
        actual_digest = payload_digest(root)
    except (TypeError, ValueError) as exc:
        raise ObservationError("integrity.payload: contains a non-finite or non-canonical value") from exc
    if not hmac.compare_digest(declared_digest, actual_digest):
        raise ObservationError("integrity.payload_sha256: payload mismatch")
    return root


def validate_and_replay(document: Any) -> dict[str, Any]:
    root = _validate_envelope(document)
    limits = _require_exact_keys(root["limits"], LIMIT_KEYS, "limits")
    if limits["height_unit"] != "normalized":
        raise ObservationError("limits.height_unit: expected normalized")
    if limits["velocity_unit"] != "normalized_per_second":
        raise ObservationError("limits.velocity_unit: expected normalized_per_second")
    if limits["time_unit"] != "milliseconds":
        raise ObservationError("limits.time_unit: expected milliseconds")
    lower = _require_number(limits["lower"], "limits.lower")
    upper = _require_number(limits["upper"], "limits.upper")
    if lower < 0.0 or upper > 1.0 or lower >= upper:
        raise ObservationError("limits: expected 0 <= lower < upper <= 1")
    max_feedback_age = _require_int(limits["max_feedback_age_ms"], "limits.max_feedback_age_ms", 1)
    max_sample_gap = _require_int(limits["max_sample_gap_ms"], "limits.max_sample_gap_ms", 1)

    samples = root["samples"]
    if not isinstance(samples, list) or len(samples) < 3:
        raise ObservationError("samples: expected at least three samples")

    previous_time: int | None = None
    requested: tuple[int, float, float] | None = None
    stopped: tuple[int, float] | None = None
    stopping_seen = False
    previous_height: float | None = None
    previous_velocity: float | None = None
    for index, raw_sample in enumerate(samples):
        location = f"samples[{index}]"
        sample = _require_exact_keys(raw_sample, SAMPLE_KEYS, location)
        sequence = _require_int(sample["sequence"], f"{location}.sequence", 1)
        if sequence != index + 1:
            raise ObservationError(f"{location}.sequence: expected {index + 1}")
        monotonic_ms = _require_int(sample["monotonic_ms"], f"{location}.monotonic_ms")
        if previous_time is not None:
            gap = monotonic_ms - previous_time
            if gap <= 0:
                raise ObservationError(f"{location}.monotonic_ms: clock did not advance")
            if gap > max_sample_gap:
                raise ObservationError(f"{location}.monotonic_ms: sample gap exceeds limit")
        previous_time = monotonic_ms

        height = _require_number(sample["height"], f"{location}.height")
        velocity = _require_number(sample["velocity"], f"{location}.velocity")
        if not lower <= height <= upper:
            raise ObservationError(f"{location}.height: outside declared soft limits")
        brake_state = sample["brake_state"]
        if brake_state not in {"engaged", "released", "unknown"}:
            raise ObservationError(f"{location}.brake_state: unknown value")
        feedback_quality = sample["feedback_quality"]
        if feedback_quality not in {"valid", "degraded", "lost"}:
            raise ObservationError(f"{location}.feedback_quality: unknown value")
        feedback_age = _require_int(sample["feedback_age_ms"], f"{location}.feedback_age_ms")
        if feedback_quality != "valid" or feedback_age > max_feedback_age:
            raise ObservationError(f"{location}: feedback is not current and valid")
        if brake_state == "unknown":
            raise ObservationError(f"{location}: brake state is unknown")
        if brake_state == "engaged" and abs(velocity) > 1e-12:
            raise ObservationError(f"{location}: engaged brake conflicts with nonzero velocity")

        stop_state = sample["stop_state"]
        if stop_state not in {"observing", "stop_requested", "stopping", "stopped"}:
            raise ObservationError(f"{location}.stop_state: unknown value")
        if stop_state == "observing":
            if requested is not None:
                raise ObservationError(f"{location}.stop_state: observing after stop request")
        elif stop_state == "stop_requested":
            if requested is not None:
                raise ObservationError(f"{location}.stop_state: duplicate stop request")
            if abs(velocity) <= 1e-12 or brake_state != "released":
                raise ObservationError(f"{location}: stop request requires motion with released brake")
            requested = (monotonic_ms, height, velocity)
            previous_height = height
            previous_velocity = velocity
        elif stop_state == "stopping":
            if requested is None or stopped is not None:
                raise ObservationError(f"{location}.stop_state: stopping outside active stop segment")
            assert previous_height is not None and previous_velocity is not None
            direction = math.copysign(1.0, requested[2])
            if velocity == 0.0 or math.copysign(1.0, velocity) != direction:
                raise ObservationError(f"{location}: stopping velocity reversed or reached zero early")
            if abs(velocity) > abs(previous_velocity) + 1e-12:
                raise ObservationError(f"{location}: stopping speed increased")
            if (height - previous_height) * direction < -1e-12:
                raise ObservationError(f"{location}: stopping displacement reversed")
            stopping_seen = True
        else:
            if requested is None or stopped is not None:
                raise ObservationError(f"{location}.stop_state: stopped outside active stop segment")
            if abs(velocity) > 1e-12 or brake_state != "engaged":
                raise ObservationError(f"{location}: stopped requires zero velocity and engaged brake")
            assert previous_height is not None
            direction = math.copysign(1.0, requested[2])
            if (height - previous_height) * direction < -1e-12:
                raise ObservationError(f"{location}: stopping displacement reversed")
            stopped = (monotonic_ms, height)
        if requested is not None:
            previous_height = height
            previous_velocity = velocity

    if requested is None or stopped is None:
        raise ObservationError("samples: one complete stop_requested -> stopped segment is required")
    if not stopping_seen:
        raise ObservationError("samples: at least one stopping sample is required")
    request_time, request_height, request_velocity = requested
    stop_time, stop_height = stopped
    displacement = stop_height - request_height
    if displacement == 0.0 or math.copysign(1.0, displacement) != math.copysign(1.0, request_velocity):
        raise ObservationError("samples: stopping displacement conflicts with initial velocity")

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "valid": True,
        "decision": "offline_observation_accepted",
        "blocking": True,
        "synthetic": True,
        "safety": dict(LOCKED_SAFETY),
        "input": {
            "schema_version": INPUT_SCHEMA_VERSION,
            "session_id": root["source"]["session_id"],
            "payload_sha256": root["integrity"]["payload_sha256"],
            "sample_count": len(samples),
        },
        "metrics": {
            "stopping_distance": abs(displacement),
            "stopping_distance_unit": "normalized",
            "stopping_duration": stop_time - request_time,
            "stopping_duration_unit": "milliseconds",
            "initial_velocity": request_velocity,
            "initial_velocity_unit": "normalized_per_second",
        },
        "limitations": [
            "synthetic_offline_data_only",
            "not_a_hardware_measurement",
            "not_a_capability_token",
        ],
    }


def failure_report(message: str) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "valid": False,
        "decision": "blocked",
        "blocking": True,
        "synthetic": True,
        "safety": dict(LOCKED_SAFETY),
        "metrics": None,
        "errors": [message],
    }


def _validate_digest_candidate(document: Any) -> dict[str, Any]:
    """Restrict digest generation to the same synthetic, non-authorizing envelope."""
    root = _require_exact_keys(document, ROOT_KEYS, "document")
    if root["schema_version"] != INPUT_SCHEMA_VERSION or root["synthetic"] is not True:
        raise ObservationError("digest: only synthetic b4.k0-observation.v1 documents are accepted")
    source = _require_exact_keys(root["source"], SOURCE_KEYS, "source")
    if source["kind"] != "synthetic_fixture" or source["device_id"] != "none":
        raise ObservationError("digest: real source is not accepted")
    safety = _require_exact_keys(root["safety"], SAFETY_KEYS, "safety")
    for key in SAFETY_KEYS:
        if _require_bool(safety[key], f"safety.{key}") is not False:
            raise ObservationError(f"safety.{key}: must remain false")
    integrity = _require_exact_keys(root["integrity"], INTEGRITY_KEYS, "integrity")
    if integrity["algorithm"] != "sha256":
        raise ObservationError("integrity.algorithm: only sha256 is supported")
    return root


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_reject_duplicate_keys)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="synthetic K0 observation JSON")
    parser.add_argument("--digest", action="store_true", help="print the canonical payload digest and exit")
    args = parser.parse_args(argv)
    try:
        document = _load_json(args.input)
        if args.digest:
            print(payload_digest(_validate_digest_candidate(document)))
            return 0
        report = validate_and_replay(document)
    except (OSError, json.JSONDecodeError, ObservationError, ValueError) as exc:
        print(json.dumps(failure_report(str(exc)), sort_keys=True, separators=(",", ":"), allow_nan=False))
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
