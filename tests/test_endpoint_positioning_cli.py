#!/usr/bin/env python3
"""Offline CLI acceptance tests for the S3 endpoint positioning report."""

import argparse
import csv
import json
import subprocess
import tempfile
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_report(report: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(report), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def load_json(path: Path) -> dict:
    require(path.is_file(), f"expected JSON output: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def assert_software_only(data: dict) -> None:
    require(data.get("serial_accessed") is False, "serial_accessed must be false")
    require(data.get("d405_accessed") is False, "d405_accessed must be false")
    require(
        data.get("motor_command_generated") is False,
        "motor_command_generated must be false",
    )
    require(data.get("nano_tested") is False, "nano_tested must be false")


def base_arguments(fixture: Path, collision_config: Path, json_path: Path,
                   csv_path: Path) -> list[str]:
    return [
        "--input", str(fixture),
        "--collision-config", str(collision_config),
        "--json", str(json_path),
        "--csv", str(csv_path),
    ]


def make_orientation_failure_fixture(source: Path, destination: Path) -> None:
    with source.open(newline="", encoding="utf-8") as input_file:
        rows = list(csv.reader(input_file))
    require(len(rows) >= 2, "orientation fixture requires at least one sample")
    # target_rz_rad is column 12 (zero-based). The current five-axis IK uses
    # rx/ry and FK deterministically reports rz=0, so this changes orientation
    # error without causing an earlier IK/workspace rejection. Keep all samples
    # for the same side consistent for repeatability-group validation.
    side = rows[1][1]
    for row in rows[1:]:
        if row[1] == side:
            row[12] = "0.0001"
    with destination.open("w", newline="", encoding="utf-8") as output_file:
        csv.writer(output_file, lineterminator="\n").writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--collision-config", required=True, type=Path)
    args = parser.parse_args()

    report = args.report.resolve()
    fixture = args.fixture.resolve()
    collision_config = args.collision_config.resolve()
    require(report.is_file(), f"report executable not found: {report}")
    require(fixture.is_file(), f"fixture not found: {fixture}")
    require(collision_config.is_file(), f"collision config not found: {collision_config}")

    with tempfile.TemporaryDirectory(prefix="s3-endpoint-positioning-cli-") as temp_name:
        temp = Path(temp_name)

        pass_json = temp / "pass.json"
        pass_csv = temp / "pass.csv"
        completed = run_report(
            report,
            base_arguments(fixture, collision_config, pass_json, pass_csv),
        )
        require(completed.returncode == 0, f"nominal fixture return code: {completed.returncode}")
        passed = load_json(pass_json)
        require(passed.get("status") == "PASS", "nominal status must be PASS")
        require(passed.get("all_samples_accepted") is True, "nominal samples must all pass")
        require(passed.get("total_samples") == 6, "nominal total_samples must be 6")
        require(passed.get("accepted_samples") == 6, "nominal accepted_samples must be 6")
        require(passed.get("rejected_samples") == 0, "nominal rejected_samples must be 0")
        require(pass_csv.is_file(), "nominal CSV output must exist")
        assert_software_only(passed)

        position_json = temp / "position-fail.json"
        position_csv = temp / "position-fail.csv"
        completed = run_report(
            report,
            base_arguments(fixture, collision_config, position_json, position_csv)
            + ["--position-tolerance-m", "0.00001"],
        )
        require(completed.returncode == 1, "strict position tolerance must return 1")
        position_failed = load_json(position_json)
        require(position_failed.get("status") == "FAIL", "position status must be FAIL")
        require(position_failed.get("all_samples_accepted") is False, "position failure must reject")
        require(position_failed.get("rejected_samples", 0) > 0, "position failure needs rejected samples")
        require(
            any(sample.get("reason") == "position_error_exceeds_tolerance"
                for sample in position_failed.get("samples", [])),
            "position rejection reason is missing",
        )
        assert_software_only(position_failed)

        orientation_fixture = temp / "orientation-failure.csv"
        make_orientation_failure_fixture(fixture, orientation_fixture)
        orientation_json = temp / "orientation-fail.json"
        orientation_csv = temp / "orientation-fail.csv"
        completed = run_report(
            report,
            base_arguments(
                orientation_fixture, collision_config, orientation_json, orientation_csv
            ) + ["--orientation-tolerance-rad", "0.000001"],
        )
        require(completed.returncode == 1, "strict orientation tolerance must return 1")
        orientation_failed = load_json(orientation_json)
        require(orientation_failed.get("status") == "FAIL", "orientation status must be FAIL")
        rejected_orientation = [
            sample for sample in orientation_failed.get("samples", [])
            if sample.get("reason") == "orientation_error_exceeds_tolerance"
        ]
        require(rejected_orientation, "orientation rejection reason is missing")
        require(
            any(sample.get("orientation_check_passed") is False
                for sample in rejected_orientation),
            "orientation_check_passed must be false",
        )
        assert_software_only(orientation_failed)

        missing_input_json = temp / "missing-input.json"
        completed = run_report(
            report,
            base_arguments(
                temp / "missing.csv", collision_config, missing_input_json,
                temp / "missing-input.csv",
            ),
        )
        require(completed.returncode == 2, "missing input must return 2")
        require(not missing_input_json.exists(), "missing input must not report PASS")

        missing_collision_json = temp / "missing-collision.json"
        completed = run_report(
            report,
            base_arguments(
                fixture, temp / "missing-collision.csv", missing_collision_json,
                temp / "missing-collision-output.csv",
            ),
        )
        require(completed.returncode == 1, "missing collision config must return 1")
        require(not missing_collision_json.exists(), "missing collision config must not report PASS")

        invalid_tolerances = (
            ("--position-tolerance-m", "0"),
            ("--position-tolerance-m", "-1"),
            ("--orientation-tolerance-rad", "0"),
            ("--orientation-tolerance-rad", "nan"),
        )
        for index, (flag, value) in enumerate(invalid_tolerances):
            completed = run_report(
                report,
                base_arguments(
                    fixture, collision_config, temp / f"invalid-{index}.json",
                    temp / f"invalid-{index}.csv",
                ) + [flag, value],
            )
            require(completed.returncode == 2, f"{flag}={value} must return 2")
            message = (completed.stdout + completed.stderr).lower()
            require("tolerance" in message or "invalid" in message,
                    f"{flag}={value} must explain invalid tolerance")

        completed = run_report(report, ["--input", str(fixture)])
        require(completed.returncode == 2, "missing required arguments must return 2")

    print("PASS: endpoint positioning CLI acceptance scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
