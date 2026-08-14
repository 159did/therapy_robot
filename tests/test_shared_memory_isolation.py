#!/usr/bin/env python3
"""Verify per-instance POSIX shared-memory isolation without robot hardware."""

import argparse
import mmap
import os
from pathlib import Path
import struct
import subprocess
import time
import uuid


DEFAULT_SHM_PATH = Path("/dev/shm/therapy_robot_shared_state")
MAGIC = 0x54524F42
VERSION = 2


def wait_until(predicate, description: str, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {description}")


def read_header(path: Path) -> tuple[int, int, int]:
    with path.open("rb", buffering=0) as stream:
        with mmap.mmap(stream.fileno(), 16, access=mmap.ACCESS_READ) as mapping:
            magic, version, heartbeat = struct.unpack_from("<IIQ", mapping)
    return magic, version, heartbeat


def start_core(main_core: Path, shm_name: str) -> subprocess.Popen[str]:
    environment = os.environ.copy()
    environment["THERAPY_ROBOT_SHM_NAME"] = shm_name
    return subprocess.Popen(
        [str(main_core)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop_core(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=3.0)
        raise AssertionError("main_core did not stop after SIGTERM")
    if process.returncode != 0:
        raise AssertionError(
            f"main_core exited with {process.returncode}: stdout={stdout!r}, stderr={stderr!r}"
        )
    return stdout, stderr


def verify_invalid_names(main_core: Path, token: str) -> None:
    invalid_names = [
        "",
        "/.",
        "/..",
        token,
        f"/{token}/child",
        f"/{token}@unsafe",
        f"/{token} space",
        "/" + token + "_" + "a" * (255 - len(token)),
    ]
    for name in invalid_names:
        before = set(Path("/dev/shm").glob(f"{token}*"))
        process = start_core(main_core, name)
        try:
            stdout, stderr = process.communicate(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.communicate(timeout=3.0)
            raise AssertionError(f"invalid shared-memory name was accepted: {name!r}")
        assert process.returncode != 0, f"invalid name returned success: {name!r}"
        assert "invalid THERAPY_ROBOT_SHM_NAME" in stderr, (
            f"missing validation diagnostic for {name!r}: stdout={stdout!r}, stderr={stderr!r}"
        )
        after = set(Path("/dev/shm").glob(f"{token}*"))
        assert after == before, f"invalid name created shared memory: {after - before}"
        assert not DEFAULT_SHM_PATH.exists(), "empty override fell back to default shared memory"


def run(main_core: Path) -> None:
    if not main_core.is_file():
        raise AssertionError(f"main_core not found: {main_core}")
    if DEFAULT_SHM_PATH.exists():
        raise AssertionError(
            f"refusing to test while the default shared memory exists: {DEFAULT_SHM_PATH}"
        )

    token = f"therapy_robot_b0_{os.getpid()}_{uuid.uuid4().hex[:10]}"
    names = [f"/{token}_a", f"/{token}_b"]
    paths = [Path("/dev/shm") / name[1:] for name in names]
    processes: list[subprocess.Popen[str]] = []
    owned_paths: set[Path] = set(paths)

    try:
        processes = [start_core(main_core, name) for name in names]
        for process, path in zip(processes, paths):
            wait_until(
                lambda process=process, path=path: path.exists() or process.poll() is not None,
                f"{path} creation",
            )
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"main_core exited before creating {path}: stdout={stdout!r}, stderr={stderr!r}"
                )

        assert paths[0].stat().st_ino != paths[1].stat().st_ino, (
            "instance names resolved to the same shared-memory object"
        )
        for path in paths:
            magic, version, first_heartbeat = read_header(path)
            assert (magic, version) == (MAGIC, VERSION), f"invalid shared-state header in {path}"
            wait_until(
                lambda path=path, first=first_heartbeat: read_header(path)[2] != first,
                f"heartbeat update in {path}",
            )

        stop_core(processes[0])
        stopped_heartbeat = read_header(paths[0])[2]
        running_heartbeat = read_header(paths[1])[2]
        time.sleep(0.25)
        assert read_header(paths[0])[2] == stopped_heartbeat, (
            "stopped instance shared memory is still being updated"
        )
        assert read_header(paths[1])[2] != running_heartbeat, (
            "stopping one instance also stopped the other instance heartbeat"
        )
        stop_core(processes[1])

        assert all(path.exists() for path in paths), (
            "one instance removed another instance's shared-memory object on exit"
        )
        assert not DEFAULT_SHM_PATH.exists(), "custom instances modified the default shared memory"
        verify_invalid_names(main_core, token)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=3.0)
        for path in owned_paths:
            path.unlink(missing_ok=True)

    assert not DEFAULT_SHM_PATH.exists(), "test cleanup touched or created default shared memory"
    print("PASS: two shared-memory instances are isolated and invalid names fail closed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-core", required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.main_core.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
