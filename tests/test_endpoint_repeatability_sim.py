#!/usr/bin/env python3
"""Acceptance tests for the software-only endpoint repeatability loop."""

import argparse
import csv
import json
import math
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


def assert_repetition_result(report: dict, table: Path, repetitions: int) -> None:
    expected_samples = 2 * repetitions
    require(report["repetitions_per_point"] == repetitions,
            "report repetition count is wrong")
    require(report["planned_samples"] == expected_samples,
            "planned sample count is wrong")
    require(report["completed_samples"] == expected_samples,
            "completed sample count is wrong")
    require(all(item["completed_repetitions"] == repetitions
                for item in report["point_summaries"]),
            "point summary repetition count is wrong")
    for point_id in ("left_15", "right_15"):
        selected = [row for row in report["samples"] if row["point_id"] == point_id]
        require([row["repetition"] for row in selected] ==
                list(range(1, repetitions + 1)),
                f"{point_id} repetition order is wrong")
        require(selected[0]["arrival_type"] == "INITIAL_APPROACH",
                "first arrival type is wrong")
        require(all(row["arrival_type"] == "RETURN_AFTER_RETREAT"
                    for row in selected[1:]),
                "later arrivals must return after retreat")
        require(all(row["retreat_completed"] is True for row in selected),
                "every measurement must be followed by retreat")
    with table.open(newline="", encoding="utf-8") as stream:
        require(len(list(csv.DictReader(stream))) == expected_samples,
                "CSV row count must match repetitions")


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
        assert_repetition_result(report, table_path, 3)
        require(report["test_mode"] == "randomized_radial_reacquisition",
                "test mode must identify randomized radial reacquisition")
        require(report["retreat_plane"] == "BASE_XY",
                "retreat plane must be BASE_XY")
        require(math.isclose(report["retreat_radius_m"], 0.015, abs_tol=1e-12),
                "default retreat radius must be 15 mm")
        require(report["random_seed"] == 20260827,
                "default random seed must be recorded")
        require(report["random_candidate_attempts"] == 36,
                "candidate attempt limit must be recorded")
        require(report["retreat_destination"] == "RANDOM_CIRCLE_POINT",
                "retreat destination must identify the random circle")
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
            require(len({row["random_angle_rad"] for row in selected}) == 3,
                    "three repetitions should use three deterministic random angles")
            for row in selected:
                target = row["target"]
                retreat = row["retreat_pose"]
                radius = math.hypot(
                    retreat["x_m"] - target["x_m"],
                    retreat["y_m"] - target["y_m"],
                )
                require(math.isclose(radius, 0.015, rel_tol=0.0, abs_tol=1e-12),
                        "retreat point must lie on the 15 mm circle")
                for axis in ("z_m", "rx_rad", "ry_rad", "rz_rad"):
                    require(math.isclose(retreat[axis], target[axis], abs_tol=1e-12),
                            f"retreat must preserve target {axis}")
                require(0.0 <= row["random_angle_rad"] < 2.0 * math.pi,
                        "random angle must be in [0, 2pi)")
                require(1 <= row["random_candidate_attempt"] <= 36,
                        "candidate attempt must be within the configured limit")
                for field in (
                    "retreat_ik_passed", "retreat_limit_passed",
                    "retreat_collision_passed", "retreat_path_passed",
                    "return_path_passed",
                ):
                    require(row[field] is True, f"safe retreat missing {field}")
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
            "random_seed", "random_candidate_attempt", "random_angle_rad",
            "retreat_radius_m", "retreat_x_m", "retreat_y_m",
            "retreat_path_passed", "return_path_passed",
            "motor_command_generated",
        ):
            require(field in rows[0], f"CSV missing field: {field}")
        require(all(row["motor_command_generated"] == "false" for row in rows),
                "CSV must not claim a motor command")

        canonical = points.read_text(encoding="utf-8").replace("\r\n", "\n")
        csv_variants = (
            ("utf8-lf", canonical.encode("utf-8")),
            ("windows-crlf", canonical.replace("\n", "\r\n").encode("utf-8")),
            ("bom-crlf", b"\xef\xbb\xbf" +
             canonical.replace("\n", "\r\n").encode("utf-8")),
            ("trimmed-fields", (
                " point_id , target_x_m , target_y_m , target_z_m , "
                "target_rx_rad , target_ry_rad , target_rz_rad \r\n"
                " left_15 , -0.0600460185 , 0.224094792 , 0.79 , 0 , 0 , 0 \r\n"
                " right_15 , 0.0600460185 , 0.224094792 , 0.79 , 0 , 0 , 0 \r\n"
            ).encode("utf-8")),
        )
        for variant_name, content in csv_variants:
            variant_points = root / f"{variant_name}.csv"
            variant_points.write_bytes(content)
            variant_output = root / variant_name
            variant_output.mkdir()
            variant_run, variant_report_path, variant_table = run_tool(
                tool, variant_points, collision, variant_output
            )
            require(variant_run.returncode == 0,
                    f"valid CSV variant failed: {variant_name}: {variant_run.stderr}")
            variant_report = load(variant_report_path)
            require(variant_report["status"] == "PASS",
                    f"valid CSV variant must pass: {variant_name}")
            assert_repetition_result(variant_report, variant_table, 3)

        invalid_csvs = (
            ("wrong-field-count",
             "point_id,target_x_m,target_y_m,target_z_m,target_rx_rad,target_ry_rad,target_rz_rad\n"
             "bad,0,0.232,0.79,0,0\n"),
            ("duplicate-id",
             "point_id,target_x_m,target_y_m,target_z_m,target_rx_rad,target_ry_rad,target_rz_rad\n"
             "same,-0.06,0.224,0.79,0,0,0\n"
             " same ,0.06,0.224,0.79,0,0,0\n"),
            ("empty-id",
             "point_id,target_x_m,target_y_m,target_z_m,target_rx_rad,target_ry_rad,target_rz_rad\n"
             "   ,0,0.232,0.79,0,0,0\n"),
            ("non-finite-number",
             "point_id,target_x_m,target_y_m,target_z_m,target_rx_rad,target_ry_rad,target_rz_rad\n"
             "bad,nan,0.232,0.79,0,0,0\n"),
        )
        for invalid_name, content in invalid_csvs:
            invalid_points = root / f"{invalid_name}.csv"
            invalid_points.write_text(content, encoding="utf-8")
            invalid_output = root / f"invalid-csv-{invalid_name}"
            invalid_output.mkdir()
            invalid_run, _, _ = run_tool(
                tool, invalid_points, collision, invalid_output
            )
            require(invalid_run.returncode == 2,
                    f"invalid CSV must return 2: {invalid_name}")

        one_repetition = root / "one-repetition"
        one_repetition.mkdir()
        one_run, one_report_path, one_table = run_tool(
            tool, points, collision, one_repetition, "--repetitions", "1"
        )
        require(one_run.returncode == 0, one_run.stderr)
        assert_repetition_result(load(one_report_path), one_table, 1)

        five_repetitions = root / "five-repetitions"
        five_repetitions.mkdir()
        five_run, five_report_path, five_table = run_tool(
            tool, points, collision, five_repetitions,
            "--repetitions", "5", "--random-seed", "20260827",
        )
        require(five_run.returncode == 0, five_run.stderr)
        five_report = load(five_report_path)
        assert_repetition_result(five_report, five_table, 5)
        require(five_report["safe_start_returned"] is True,
                "five-repetition run must return safe start")

        deterministic = root / "deterministic"
        deterministic.mkdir()
        repeated, repeated_report, repeated_table = run_tool(
            tool, points, collision, deterministic,
            "--repetitions", "5", "--random-seed", "20260827",
        )
        require(repeated.returncode == 0, repeated.stderr)
        require(five_report_path.read_bytes() == repeated_report.read_bytes(),
                "same input, seed and repetitions must generate deterministic JSON")
        require(five_table.read_bytes() == repeated_table.read_bytes(),
                "same input, seed and repetitions must generate deterministic CSV")

        different_seed = root / "different-seed"
        different_seed.mkdir()
        changed, changed_report_path, _ = run_tool(
            tool, points, collision, different_seed,
            "--repetitions", "5", "--random-seed", "7",
        )
        require(changed.returncode == 0, changed.stderr)
        changed_report = load(changed_report_path)
        require(changed_report["random_seed"] == 7, "overridden seed must be recorded")
        require(
            [row["random_angle_rad"] for row in changed_report["samples"]]
            != [row["random_angle_rad"] for row in five_report["samples"]],
            "different seed must change the retreat points",
        )

        for number, arguments in enumerate((
            ("--retreat-radius-m", "0"),
            ("--retreat-radius-m", "nan"),
            ("--random-seed", "4294967296"),
            ("--random-seed", "-1"),
            ("--random-candidate-attempts", "0"),
            ("--repetitions", "0"),
            ("--repetitions", "-1"),
            ("--repetitions", "1.5"),
            ("--repetitions", "abc"),
            ("--repetitions", "101"),
        )):
            invalid = root / f"invalid-{number}"
            invalid.mkdir()
            rejected_option, _, _ = run_tool(
                tool, points, collision, invalid, *arguments
            )
            require(rejected_option.returncode == 2,
                    f"invalid option must return 2: {arguments}")

        no_candidate = root / "no-safe-candidate"
        no_candidate.mkdir()
        completed, no_candidate_report, _ = run_tool(
            tool, points, collision, no_candidate,
            "--retreat-radius-m", "10",
            "--random-candidate-attempts", "3",
        )
        require(completed.returncode == 1,
                "all unsafe retreat candidates must return 1")
        candidate_failure = load(no_candidate_report)
        require(candidate_failure["status"] == "FAIL",
                "all unsafe candidates must fail")
        require(candidate_failure["final_state"] == "STOPPED",
                "all unsafe candidates must stop")
        require(candidate_failure["failure_reason"] ==
                "no_safe_random_retreat_point",
                "candidate exhaustion reason must be explicit")
        assert_no_entity_action(candidate_failure)

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
