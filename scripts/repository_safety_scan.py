#!/usr/bin/env python3
"""Report likely publication-sensitive tracked files without modifying them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


EXACT_PATHS = {
    "machine_local_hardware_config": ("config/jetson-hardware.env",),
}

PATTERNS = {
    "entity_calibration_or_observation": (
        "calibration/axis-offsets-native_",
        "calibration/five_axis_",
        "calibration/k0-",
        "calibration/K0",
        "calibration/k0_",
        "calibration/camera_to_base_samples",
    ),
    "captured_back_sample": ("data/d405_samples/", "back/back.png"),
}


def run(root: Path) -> dict:
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files"], text=True).splitlines()
    findings = {
        category: [path for path in tracked if path in paths]
        for category, paths in EXACT_PATHS.items()
    }
    findings.update({
        category: [path for path in tracked if any(pattern in path for pattern in patterns)]
        for category, patterns in PATTERNS.items()
    })
    return {
        "schema_version": "repository.safety-scan.v1",
        "read_only": True,
        "tracked_file_count": len(tracked),
        "findings": findings,
        "publication_blocking": any(findings.values()),
        "recommendation": (
            "Keep the repository private. Before any public release, move or replace each finding "
            "with a synthetic/example artifact and remove it from Git history if it was sensitive."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps(run(args.root.resolve()), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
