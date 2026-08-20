#!/usr/bin/env python3
"""Run the checked-in B5 route -> vision -> DEMO flow offline.

This orchestration layer reads existing JSON results and delegates validation
to ``b5_demo_adapter``. It does not invoke producers, hardware, or services.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VISION = ROOT / "docs" / "progress" / "evidence" / "B5" / "DEMO" / "vision-from-b5-vision.json"
DEFAULT_ROUTES = {
    "left": ROOT / "docs" / "progress" / "evidence" / "B5" / "DEMO" / "route-left-from-b5-m1-m2.json",
    "right": ROOT / "docs" / "progress" / "evidence" / "B5" / "DEMO" / "route-right-from-b5-m1-m2.json",
}


def load_adapter_run():
    adapter_path = Path(__file__).resolve().with_name("b5_demo_adapter.py")
    spec = importlib.util.spec_from_file_location("b5_demo_adapter_for_offline_demo", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("demo_adapter_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run

def run_demo(side: str, route: Path | None = None, vision: Path | None = None, expected_route_sha256: str | None = None, expected_vision_sha256: str | None = None) -> dict[str, Any]:
    if side not in DEFAULT_ROUTES:
        raise ValueError("side_invalid")
    route_path = (route or DEFAULT_ROUTES[side]).resolve()
    vision_path = (vision or DEFAULT_VISION).resolve()
    report = load_adapter_run()(route_path, vision_path, side, expected_route_sha256, expected_vision_sha256)
    report["orchestration"] = {
        "schema_version": "b5.offline-demo-orchestration.v1",
        "route_path": str(route_path),
        "vision_path": str(vision_path),
        "producer_invoked": False,
        "hardware_accessed": False,
        "service_started": False,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--route", type=Path)
    parser.add_argument("--vision", type=Path)
    parser.add_argument("--expected-route-sha256")
    parser.add_argument("--expected-vision-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_demo(args.side, args.route, args.vision, args.expected_route_sha256, args.expected_vision_sha256)
    except Exception as exc:
        report = {"valid": False, "current_stage": "BLOCKED", "final_state": "BLOCKED", "side": args.side, "blocking_reasons": [str(exc)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "current_stage": report["current_stage"], "side": report["side"], "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
