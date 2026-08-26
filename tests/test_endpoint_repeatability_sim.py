#!/usr/bin/env python3
"""Acceptance tests for the software-only endpoint repeatability loop."""

import argparse
import csv
import json
import subprocess
import tempfile
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_tool(tool: Path, points: Path, collision: Path, directory: Path,
             *extra: str) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    report = directory / "report.json"
    table = directory / "table.csv"
    completed = subprocess.run(
        [str(tool), "--points", str(points), "--collision-config", str(collision),
         "--json", str(report), "--csv", str(table), *extra],
        check=False, capture_output=True, text=True,
    )
    return completed, report, table


def load(path: Path) -> dict:
    require(path.is_file(), f"missing report: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def assert_no_entity_action(report: dict) -> None:
    for key in (
        "execution_allowed", "entity_action_authorized",
        "entity_motion_authorized", "motor_command_generated",
        "motor_target_generated", "serial_payload_generated",
        "shared_memory_written", "serial_accessed", "d405_accessed",
        "nano_tested", "arm64_tested", "entity_hardware_tested",
    ):
        require(report.get(key) is False, f"{key} must be false")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True, type=Path)
    parser.add_argument("--points", required=True, type=Path)
    parser.add_argument("--collision-config", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    tool = args.tool.resolve()
    points = args.points.resolve()
    collision = args.collision_config.resolve()
    source = args.source.resolve()

    with tempfile.TemporaryDirectory(prefix="s3-repeatability-sim-") as name:
        root = Path(name)
        normal = root / "normal"
        normal.mkdir()
        completed, report_path, table_path = run_tool(tool, points, collision, normal)
        require(completed.returncode == 0, completed.stderr)
        report = load(report_path)
        require(report["status"] == "PASS", "normal status must be PASS")
        require(report["final_state"] == "COMPLETE", "normal run must complete")
        require(report["selected_points"] == 2, "fixture must select two points")
        require(report["repetitions_per_point"] == 3, "each point must run three times")
        require(report["planned_samples"] == 6, "two points must plan six samples")
        require(report["completed_samples"] == 6, "all six samples must complete")
        require(report["safe_start_returned"] is True, "run must return safe start")
        require(all(item["completed_repetitions"] == 3
                    for item in report["point_summaries"]),
                "each point summary must contain three repetitions")
        for summary in report["point_summaries"]:
            for field in (
                "mean_actual_xyz_m", "mean_position_error_m",
                "max_position_error_m", "rms_position_error_m",
                "mean_repeatability_error_m", "max_repeatability_error_m",
                "rms_repeatability_error_m", "stddev_repeatability_error_m",
            ):
                require(field in summary, f"point summary missing: {field}")
        for point_id in ("left_15", "right_15"):
            selected = [row for row in report["samples"] if row["point_id"] == point_id]
            require([row["repetition"] for row in selected] == [1, 2, 3],
                    f"{point_id} repetition order is wrong")
            require(selected[0]["arrival_type"] == "INITIAL_APPROACH",
                    "first arrival type is wrong")
            require(all(row["arrival_type"] == "RETURN_AFTER_RETREAT"
                        for row in selected[1:]),
                    "later arrivals must return after retreat")
            require(all(row["retreat_completed"] is True for row in selected),
                    "every measurement must be followed by retreat")
            require(all(row["feedback_valid"] is True for row in selected),
                    "normal feedback must be valid")
        states = [event["state"] for event in report["events"]]
        for state in (
            "READY", "MOVING_TO_TARGET", "WAITING_TARGET_SETTLE",
            "CAPTURING_FEEDBACK", "RETREATING", "WAITING_RETREAT_SETTLE",
            "RETURNING_SAFE", "COMPLETE",
        ):
            require(state in states, f"missing state: {state}")
        assert_no_entity_action(report)
        require(table_path.is_file(), "CSV table must exist")
        with table_path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        require(len(rows) == 6, "CSV must contain one row per repetition")
        for field in (
            "target_x_m", "actual_k0_m", "actual_x_m", "position_error_m",
            "orientation_error_rad", "move_duration_ms", "retreat_completed",
            "motor_command_generated",
        ):
            require(field in rows[0], f"CSV missing field: {field}")
        require(all(row["motor_command_generated"] == "false" for row in rows),
                "CSV must not claim a motor command")

        deterministic = root / "deterministic"
        deterministic.mkdir()
        repeated, repeated_report, repeated_table = run_tool(
            tool, points, collision, deterministic
        )
        require(repeated.returncode == 0, repeated.stderr)
        require(report_path.read_bytes() == repeated_report.read_bytes(),
                "same input must generate deterministic JSON")
        require(table_path.read_bytes() == repeated_table.read_bytes(),
                "same input must generate deterministic CSV")

        timeout = root / "timeout"
        timeout.mkdir()
        completed, timeout_report, _ = run_tool(
            tool, points, collision, timeout, "--move-timeout-ms", "1"
        )
        require(completed.returncode == 1, "move timeout must return 1")
        timed_out = load(timeout_report)
        require(timed_out["status"] == "FAIL", "timeout status must be FAIL")
        require(timed_out["final_state"] == "STOPPED", "timeout must stop")
        require(timed_out["failure_reason"] == "move_timeout",
                "timeout reason must be explicit")
        assert_no_entity_action(timed_out)

        settle = root / "settle-timeout"
        settle.mkdir()
        completed, settle_report, _ = run_tool(
            tool, points, collision, settle, "--settle-timeout-ms", "1"
        )
        require(completed.returncode == 1, "settle timeout must return 1")
        settle_timed_out = load(settle_report)
        require(settle_timed_out["final_state"] == "STOPPED",
                "settle timeout must stop")
        require(settle_timed_out["failure_reason"] == "settle_timeout",
                "settle timeout reason must be explicit")
        assert_no_entity_action(settle_timed_out)

        feedback = root / "feedback-loss"
        feedback.mkdir()
        completed, feedback_report, _ = run_tool(
            tool, points, collision, feedback,
            "--simulate-feedback-loss-at", "left_15:2",
        )
        require(completed.returncode == 1, "feedback loss must return 1")
        feedback_lost = load(feedback_report)
        require(feedback_lost["status"] == "FAIL", "feedback loss must fail")
        require(feedback_lost["final_state"] == "STOPPED", "feedback loss must stop")
        require(feedback_lost["failure_reason"] == "feedback_lost",
                "feedback loss reason must be explicit")
        require(feedback_lost["completed_samples"] == 1,
                "feedback loss at left_15:2 must preserve one completed sample")
        assert_no_entity_action(feedback_lost)

        unreachable_points = root / "unreachable.csv"
        unreachable_points.write_text(
            "point_id,target_x_m,target_y_m,target_z_m,target_rx_rad,target_ry_rad,target_rz_rad\n"
            "outside,2,0,0.8,0,0,0\n",
            encoding="utf-8",
        )
        unreachable = root / "unreachable"
        unreachable.mkdir()
        completed, unreachable_report, _ = run_tool(
            tool, unreachable_points, collision, unreachable
        )
        require(completed.returncode == 1, "unreachable point must return 1")
        rejected = load(unreachable_report)
        require(rejected["final_state"] == "STOPPED",
                "unreachable point must stop")
        require(rejected["failure_reason"].startswith("target_preflight_rejected:"),
                "unreachable point rejection must identify preflight")
        assert_no_entity_action(rejected)

    source_text = source.read_text(encoding="utf-8")
    for forbidden in (
        "/dev/tty", "run-jetson-hardware", "main_motor", "shm_open(",
        "write(", "D405", "enable_all", "jog_axis", "endpoint_target",
    ):
        require(forbidden not in source_text,
                f"simulator source contains forbidden hardware operation: {forbidden}")
    print("PASS: endpoint repeatability automatic simulation loop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
