#!/usr/bin/env python3
"""Capture a D405 RGB-D bundle without touching robot control.

Default mode is a configuration/help preflight and never opens a camera. Use
``--live`` explicitly on a host with pyrealsense2 installed. The script only
opens the camera, waits for aligned RGB/depth frames, and writes a self-
contained bundle for the offline vision pipeline; it never opens a serial
port, shared memory, or motor service.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "ptr.d405-capture-bundle.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bundle_metadata(output: Path, serial: str | None, width: int, height: int, fps: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "captured_at_utc": utc_now(),
        "host": {"hostname": platform.node(), "architecture": platform.machine()},
        "camera": {"model": "Intel RealSense D405", "serial": serial, "width": width, "height": height, "fps": fps},
        "hardware_access": {
            "d405_accessed": True,
            "camera_device_opened": True,
            "nano_accessed": False,
            "serial_accessed": False,
            "motor_command_generated": False,
        },
        "robot_control": {
            "motor_enabled": False,
            "motor_moved": False,
            "entity_action_authorized": False,
            "execution_allowed": False,
        },
        "output_dir": str(output),
    }


def capture(args: argparse.Namespace) -> int:
    if not args.live:
        print(json.dumps({"ok": True, "mode": "preflight", "live": False, "message": "未使用 --live，不会打开 D405"}, ensure_ascii=False))
        return 0
    try:
        rs = importlib.import_module("pyrealsense2")
    except ImportError as exc:
        print(json.dumps({"ok": False, "error": "pyrealsense2_missing", "message": str(exc)}, ensure_ascii=False))
        return 2

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    pipeline = rs.pipeline()
    config = rs.config()
    if args.serial:
        config.enable_device(args.serial)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.rgb8, args.fps)
    config.enable_stream(rs.stream.depth, args.width, args.height, rs.format.z16, args.fps)
    align = rs.align(rs.stream.color)
    profile = None
    try:
        profile = pipeline.start(config)
        device = profile.get_device()
        device_serial = device.get_info(rs.camera_info.serial_number)
        for _ in range(max(1, args.warmup_frames)):
            pipeline.wait_for_frames(timeout_ms=args.timeout_ms)
        frames = pipeline.wait_for_frames(timeout_ms=args.timeout_ms)
        aligned = align.process(frames)
        color = aligned.get_color_frame()
        depth = aligned.get_depth_frame()
        if not color or not depth:
            raise RuntimeError("aligned_rgb_depth_missing")
        import numpy as np
        from PIL import Image

        color_array = np.asanyarray(color.get_data())
        depth_array = np.asanyarray(depth.get_data())
        if color_array.ndim != 3 or depth_array.ndim != 2:
            raise RuntimeError("capture_dimensions_invalid")
        color_path = output / "rgb.png"
        depth_path = output / "depth_z16.npy"
        meta_path = output / "meta.json"
        Image.fromarray(color_array).save(color_path)
        np.save(depth_path, depth_array)
        intrinsics = color.profile.as_video_stream_profile().get_intrinsics()
        depth_sensor = device.first_depth_sensor()
        metadata = bundle_metadata(output, device_serial, color_array.shape[1], color_array.shape[0], args.fps)
        metadata["intrinsics"] = {"fx": intrinsics.fx, "fy": intrinsics.fy, "ppx": intrinsics.ppx, "ppy": intrinsics.ppy}
        metadata["depth_scale_m_per_unit"] = float(depth_sensor.get_depth_scale())
        metadata["files"] = {"rgb": color_path.name, "depth": depth_path.name, "meta": meta_path.name}
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest = output / "SHA256SUMS"
        manifest.write_text("\n".join(f"{sha256_file(path)}  {path.name}" for path in (color_path, depth_path, meta_path)) + "\n", encoding="ascii")
        print(json.dumps({"ok": True, "bundle": str(output), "serial": device_serial, "rgb": str(color_path), "depth": str(depth_path), "meta": str(meta_path), "sha256": str(manifest)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "bundle": str(output)}, ensure_ascii=False))
        return 2
    finally:
        if profile is not None:
            pipeline.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/d405_captures/latest"))
    parser.add_argument("--serial", help="D405 serial number")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--warmup-frames", type=int, default=30)
    parser.add_argument("--timeout-ms", type=int, default=3000)
    parser.add_argument("--live", action="store_true", help="explicitly open D405 and capture one aligned frame")
    args = parser.parse_args(argv)
    if args.width <= 0 or args.height <= 0 or args.fps <= 0 or args.timeout_ms <= 0:
        parser.error("width/height/fps/timeout must be positive")
    return capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
