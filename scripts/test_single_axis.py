#!/usr/bin/env python3
"""Safely issue one small joint jog through the therapy robot web API."""

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request


AXES = {f"K{index}": index for index in range(5)}


def request_json(base_url, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error


def motor_for_axis(state, axis):
    mapping = state["axis_map"][axis]
    return state["groups"][mapping["group"]]["motors"][mapping["axis"]], mapping


def print_status(state, selected_axis=None):
    print(f"mode={state.get('run_mode')} system={state.get('system_state')} "
          f"emergency_stop={state.get('emergency_stop')}")
    for axis in range(5):
        motor, mapping = motor_for_axis(state, axis)
        scale = float(mapping["motor_native_to_gui_display"])
        value = int(motor["actual_motor_native"]) * scale
        marker = "*" if selected_axis == axis else " "
        brake = ""
        if motor.get("brake_supported"):
            known = motor.get("brake_state_known")
            brake = f" brake={'engaged' if motor.get('brake_engaged') else 'released'}" if known else " brake=unknown"
        print(f"{marker} K{axis}: actual={value:.3f} {mapping['gui_display_unit']} "
              f"native={motor['actual_motor_native']} online={motor['online']} "
              f"enabled={motor['enabled']} fault={motor['fault']}{brake}")


def wait_for_target(base_url, axis, target_native, timeout):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = request_json(base_url, "/api/state")
        motor, _ = motor_for_axis(latest, axis)
        if abs(int(motor["actual_motor_native"]) - target_native) <= 1:
            return latest
        time.sleep(0.1)
    raise RuntimeError(f"timeout waiting for K{axis} target; last state follows\n{json.dumps(latest, ensure_ascii=False)}")


def main():
    parser = argparse.ArgumentParser(
        description="Test one joint at a time. This tool never enables motors automatically.")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--wait", type=float, default=5.0,
                        help="seconds to wait for jog feedback (default: 5)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("enable")
    sub.add_parser("stop")
    sub.add_parser("disable")
    jog = sub.add_parser("jog")
    jog.add_argument("axis", choices=AXES, type=str.upper)
    jog.add_argument("delta", type=float, help="K0 uses mm; K1-K4 use deg")
    args = parser.parse_args()

    if args.command == "status":
        print_status(request_json(args.url, "/api/state"))
        return 0
    if args.command == "enable":
        print("Requesting enable only; no movement command is sent.")
        print(json.dumps(request_json(args.url, "/api/command/enable_all", {}), ensure_ascii=False))
        return 0
    if args.command == "stop":
        print(json.dumps(request_json(args.url, "/api/command/stop_all", {}), ensure_ascii=False))
        return 0
    if args.command == "disable":
        print(json.dumps(request_json(args.url, "/api/command/disable_all", {}), ensure_ascii=False))
        return 0

    axis = AXES[args.axis]
    if not math.isfinite(args.delta) or args.delta == 0 or abs(args.delta) > 5:
        parser.error("delta must be non-zero and no greater than 5 mm/deg")
    if axis == 0:
        print("WARNING: K0 is the gravity axis. Support the arm and verify the brake before jogging.")
    before = request_json(args.url, "/api/state")
    print("Before:")
    print_status(before, axis)
    result = request_json(args.url, "/api/command/jog_axis", {
        "axis": axis,
        "delta_display": args.delta,
    })
    print("Accepted:", json.dumps(result, ensure_ascii=False))
    after = wait_for_target(args.url, axis, int(result["target_native"]), args.wait)
    print("After:")
    print_status(after, axis)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
