#!/usr/bin/env python3
"""Pure normalized-unit M1/M2 motion preparation simulator.

This module deliberately models intent and safety facts only. It has no motor,
shared-memory, serial, deployment, or executable-target interface.
"""

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


INPUT_SCHEMA = "b4.m1-m2-sim-input.v1"
OUTPUT_SCHEMA = "b4.m1-m2-sim.v1"
TOOL_VERSION = "b4-prep-c.1"
ALLOWED_ACTIONS = ("high_lift", "lateral_expand", "retract", "high_return", "stow")
REQUIRED_INPUT = {"schema_version", "synthetic", "source", "units", "scenario", "config", "segments", "payload_sha256"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(document):
    unsigned = dict(document)
    unsigned.pop("payload_sha256", None)
    return hashlib.sha256(canonical(unsigned).encode("utf-8")).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("non_finite_" + name)
    return float(value)


def integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid_" + name)
    return value


def validate_input(document):
    if not isinstance(document, dict):
        raise ValueError("input_not_object")
    unknown = set(document) - REQUIRED_INPUT
    missing = REQUIRED_INPUT - set(document)
    if unknown:
        raise ValueError("unknown_input_fields:" + ",".join(sorted(unknown)))
    if missing:
        raise ValueError("missing_input_fields:" + ",".join(sorted(missing)))
    if document["schema_version"] != INPUT_SCHEMA or document["synthetic"] is not True:
        raise ValueError("synthetic_schema_or_flag_invalid")
    if not isinstance(document["source"], dict) or set(document["source"]) != {"kind", "fixture_id"} or document["source"]["kind"] != "synthetic_fixture" or not isinstance(document["source"]["fixture_id"], str) or not document["source"]["fixture_id"]:
        raise ValueError("synthetic_source_invalid")
    if not isinstance(document["units"], dict) or document["units"] != {"position": "normalized", "speed": "normalized_per_second", "time": "milliseconds"}:
        raise ValueError("simulation_units_invalid")
    if document["scenario"] not in ("nominal", "emergency_stop", "watchdog_timeout", "feedback_loss"):
        raise ValueError("scenario_invalid")
    config = document["config"]
    if not isinstance(config, dict) or set(config) != {"min_speed_norm_s", "min_displacement_norm", "stop_decel_norm_s2", "watchdog_timeout_ms", "sample_period_ms"}:
        raise ValueError("simulation_config_invalid")
    min_speed = finite(config["min_speed_norm_s"], "min_speed_norm_s")
    min_displacement = finite(config["min_displacement_norm"], "min_displacement_norm")
    stop_decel = finite(config["stop_decel_norm_s2"], "stop_decel_norm_s2")
    watchdog = integer(config["watchdog_timeout_ms"], "watchdog_timeout_ms")
    sample_period = integer(config["sample_period_ms"], "sample_period_ms")
    if min_speed <= 0 or min_displacement <= 0 or stop_decel <= 0 or watchdog <= 0 or sample_period <= 0:
        raise ValueError("simulation_config_non_positive")
    if watchdog < sample_period:
        raise ValueError("watchdog_shorter_than_sample_period")
    segments = document["segments"]
    if not isinstance(segments, list) or not segments:
        raise ValueError("segments_missing")
    seen_sides = set()
    clean_segments = []
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != {"side", "actions"}:
            raise ValueError("segment_schema_invalid")
        side = segment["side"]
        if side not in ("left", "right") or side in seen_sides:
            raise ValueError("segment_side_invalid_or_duplicate")
        seen_sides.add(side)
        actions = segment["actions"]
        if not isinstance(actions, list) or [item.get("kind") for item in actions if isinstance(item, dict)] != list(ALLOWED_ACTIONS):
            raise ValueError("route_action_order_invalid")
        clean_actions = []
        for index, action in enumerate(actions):
            if not isinstance(action, dict) or set(action) != {"kind", "distance_norm", "speed_norm_s"}:
                raise ValueError("action_schema_invalid")
            if action["kind"] != ALLOWED_ACTIONS[index]:
                raise ValueError("route_action_order_invalid")
            distance = finite(action["distance_norm"], "distance_norm")
            speed = finite(action["speed_norm_s"], "speed_norm_s")
            if distance < min_displacement or speed < min_speed:
                raise ValueError("minimum_motion_threshold_not_met")
            clean_actions.append({"kind": action["kind"], "distance_norm": distance, "speed_norm_s": speed})
        clean_segments.append({"side": side, "actions": clean_actions})
    if seen_sides != {"left", "right"}:
        raise ValueError("both_left_and_right_segments_required")
    if document["payload_sha256"] != payload_sha256(document):
        raise ValueError("payload_sha256_mismatch")
    return {"document": document, "config": config, "segments": clean_segments}


def simulate(model):
    config = model["config"]
    states = []
    events = []
    total_duration = 0
    max_stop_distance = 0.0
    action_count = 0
    final_state = {"height_norm": 0.0, "lateral_norm": 0.0, "phase": "STOWED"}
    fault = model["document"].get("scenario")
    fault_mode = fault if fault in ("emergency_stop", "watchdog_timeout", "feedback_loss") else None
    for segment in model["segments"]:
        for action in segment["actions"]:
            action_count += 1
            distance = action["distance_norm"]
            speed = action["speed_norm_s"]
            duration = int(math.ceil(distance / speed * 1000.0))
            stopping_distance = speed * speed / (2.0 * float(config["stop_decel_norm_s2"]))
            max_stop_distance = max(max_stop_distance, stopping_distance)
            if stopping_distance > distance:
                raise ValueError("stopping_distance_exceeds_segment")
            total_duration += duration
            states.append({"side": segment["side"], "phase": action["kind"], "duration_ms": duration, "distance_norm": distance, "speed_norm_s": speed, "stopping_distance_norm": stopping_distance})
            if action["kind"] == "high_lift" or action["kind"] == "high_return":
                final_state["height_norm"] = distance if action["kind"] == "high_lift" else 0.0
                final_state["phase"] = "HIGH_LIFT" if action["kind"] == "high_lift" else "HIGH_RETURN"
            elif action["kind"] == "lateral_expand":
                final_state["lateral_norm"] = distance; final_state["phase"] = "LATERAL_EXPAND"
            elif action["kind"] == "retract":
                final_state["lateral_norm"] = 0.0; final_state["phase"] = "RETRACT"
            elif action["kind"] == "stow":
                final_state = {"height_norm": 0.0, "lateral_norm": 0.0, "phase": "STOWED"}
            if fault_mode and action_count == 3:
                reason = {"emergency_stop": "emergency_stop_requested", "watchdog_timeout": "watchdog_timeout", "feedback_loss": "feedback_loss"}[fault_mode]
                events.extend([{"event": "stop_requested", "reason_code": reason}, {"event": "stopping", "reason_code": reason}, {"event": "stopped", "reason_code": "safe_stop"}])
                return {"states": states, "events": events, "total_duration_ms": total_duration, "max_stop_distance_norm": max_stop_distance, "action_count": action_count, "final_state": {"height_norm": 0.0, "lateral_norm": 0.0, "phase": "STOPPED"}, "fault_handled": True, "fault_mode": fault_mode}
    return {"states": states, "events": [{"event": "completed", "reason_code": "route_complete"}], "total_duration_ms": total_duration, "max_stop_distance_norm": max_stop_distance, "action_count": action_count, "final_state": final_state, "fault_handled": False, "fault_mode": None}


def report(model, result, source_path):
    fault_expected = result["fault_mode"] is not None
    checks = [
        {"id": "synthetic_source", "status": "pass", "value": True, "threshold": True, "reason_code": "ok"},
        {"id": "minimum_speed_and_displacement", "status": "pass", "value": True, "threshold": True, "reason_code": "ok"},
        {"id": "route_order_and_sides", "status": "pass", "value": result["action_count"], "threshold": 10, "reason_code": "ok"},
        {"id": "stop_distance_model", "status": "pass", "value": result["max_stop_distance_norm"], "threshold": "segment_distance", "reason_code": "ok"},
        {"id": "fault_safe_stop", "status": "pass", "value": result["fault_handled"] if fault_expected else True, "threshold": True, "reason_code": "safe_stop" if fault_expected else "not_injected"},
    ]
    speeds = [action["speed_norm_s"] for segment in model["segments"] for action in segment["actions"]]
    displacements = [action["distance_norm"] for segment in model["segments"] for action in segment["actions"]]
    core = {"schema_version": OUTPUT_SCHEMA, "tool_version": TOOL_VERSION, "scenario": model["document"]["scenario"], "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(), "metrics": {"total_duration_ms": result["total_duration_ms"], "max_stop_distance_norm": result["max_stop_distance_norm"], "minimum_speed_norm_s": min(speeds), "minimum_displacement_norm": min(displacements), "watchdog_timeout_ms": model["config"]["watchdog_timeout_ms"], "action_count": result["action_count"]}, "final_state": result["final_state"], "events": result["events"], "checks": checks}
    core["simulation_id"] = "sim-" + hashlib.sha256(canonical(core).encode("utf-8")).hexdigest()[:24]
    return {"schema_version": OUTPUT_SCHEMA, "tool_version": TOOL_VERSION, "generated_at_utc": utc_now(), "simulation_id": core["simulation_id"], "simulation_valid": True, "synthetic": True, "formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False, "recovery_allowed": False, "resume_requires_new_authorization": True, "source": {"path": str(source_path), "sha256": core["source_sha256"]}, "units": model["document"]["units"], "scenario": core["scenario"], "metrics": core["metrics"], "final_state": core["final_state"], "events": core["events"], "checks": checks, "blocking_reasons": [], "route_trace": result["states"]}


def atomic_write(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True); stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay a normalized-unit B4-PREP M1/M2 route")
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", "--output", dest="out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.input.resolve() == args.out.resolve():
        parser.error("output must not overwrite the input")
    try:
        source = args.input.resolve()
        model = validate_input(json.loads(source.read_text(encoding="utf-8")))
        result = report(model, simulate(model), source)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        result = {"schema_version": OUTPUT_SCHEMA, "tool_version": TOOL_VERSION, "generated_at_utc": utc_now(), "simulation_id": None, "simulation_valid": False, "synthetic": True, "formal_use_allowed": False, "promotion_locked": True, "execution_allowed": False, "entity_action_authorized": False, "nano_deployment_authorized": False, "recovery_allowed": False, "resume_requires_new_authorization": True, "checks": [{"id": "input", "status": "unknown", "value": None, "threshold": None, "reason_code": str(error)}], "blocking_reasons": [str(error)]}
    atomic_write(args.out, result)
    print(json.dumps({"ok": result["simulation_valid"], "out": str(args.out), "simulation_id": result["simulation_id"], "blocking_reasons": result["blocking_reasons"]}, ensure_ascii=False, indent=2))
    return 0 if result["simulation_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
