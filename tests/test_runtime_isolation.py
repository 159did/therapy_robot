#!/usr/bin/env python3
"""Verify runtime directories, web ports, logs and PID cleanup are isolated."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid


DEFAULT_SHM_PATH = Path("/dev/shm/therapy_robot_shared_state")
DEFAULT_RUNTIME_DIR = Path("/tmp/therapy_robot")


def wait_until(predicate, description: str, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {description}")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_process(binary: Path, environment: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [str(binary)],
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def get_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(port: int, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_web(port: int, process: subprocess.Popen[str]) -> None:
    def ready() -> bool:
        if process.poll() is not None:
            return True
        try:
            return "core_heartbeat_ms" in get_json(port, "/api/state")
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return False

    try:
        wait_until(ready, f"web port {port}")
    except AssertionError as exc:
        if process.poll() is None:
            process.terminate()
        stdout, stderr = process.communicate(timeout=3.0)
        raise AssertionError(
            f"{exc}: stdout={stdout!r}, stderr={stderr!r}"
        ) from exc
    if process.poll() is not None:
        stdout, stderr = process.communicate()
        raise AssertionError(
            f"main_web_control exited before listening: stdout={stdout!r}, stderr={stderr!r}"
        )


def process_start_time(pid: int) -> str:
    fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
    return fields[19]


def write_process_registry(runtime_dir: Path, processes: list[tuple[int, str]]) -> None:
    with (runtime_dir / "processes.pid").open("w", encoding="ascii") as stream:
        for pid, name in processes:
            stream.write(f"{pid} {process_start_time(pid)} {name}\n")


def process_exited(process: subprocess.Popen[str]) -> bool:
    return process.poll() is not None


def stop_and_reap(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.communicate(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=3.0)
        raise AssertionError("test process did not stop")


def directory_signature(path: Path) -> list[tuple[str, int, int]]:
    if not path.exists():
        return []
    return sorted(
        (str(item.relative_to(path)), item.stat().st_size, item.stat().st_mtime_ns)
        for item in path.rglob("*")
        if item.is_file()
    )


def verify_invalid_web_config(main_web: Path, main_core: Path, repo: Path, token: str) -> None:
    shm_name = f"/therapy_robot_{token}_invalid"
    shm_path = Path("/dev/shm") / shm_name[1:]
    runtime_path = Path(f"/tmp/therapy_robot_{token}_invalid")
    core_env = os.environ.copy()
    core_env["THERAPY_ROBOT_SHM_NAME"] = shm_name
    core = start_process(main_core, core_env, repo)
    try:
        wait_until(shm_path.exists, f"{shm_path} creation")
        invalid_cases = [
            ({"THERAPY_ROBOT_RUNTIME_DIR": ""}, "THERAPY_ROBOT_RUNTIME_DIR"),
            ({"THERAPY_ROBOT_RUNTIME_DIR": "relative-runtime"}, "THERAPY_ROBOT_RUNTIME_DIR"),
            ({"THERAPY_ROBOT_WEB_PORT": "abc"}, "THERAPY_ROBOT_WEB_PORT"),
            ({"THERAPY_ROBOT_WEB_PORT": "0"}, "THERAPY_ROBOT_WEB_PORT"),
            ({"THERAPY_ROBOT_WEB_PORT": "65536"}, "THERAPY_ROBOT_WEB_PORT"),
        ]
        for overrides, diagnostic in invalid_cases:
            environment = os.environ.copy()
            environment.update(
                {
                    "THERAPY_ROBOT_SHM_NAME": shm_name,
                    "THERAPY_ROBOT_COLLISION_REQUIRED": "0",
                    "THERAPY_ROBOT_ROOT": str(repo),
                    "THERAPY_ROBOT_RUNTIME_DIR": str(runtime_path),
                    "THERAPY_ROBOT_WEB_PORT": str(free_port()),
                }
            )
            environment.update(overrides)
            process = start_process(main_web, environment, repo)
            stdout, stderr = process.communicate(timeout=3.0)
            assert process.returncode != 0, f"invalid web configuration was accepted: {overrides}"
            assert diagnostic in stderr, (
                f"missing diagnostic for {overrides}: stdout={stdout!r}, stderr={stderr!r}"
            )
    finally:
        stop_and_reap(core)
        shm_path.unlink(missing_ok=True)
        shutil.rmtree(runtime_path, ignore_errors=True)


def run(main_core: Path, main_web: Path, kill_script: Path) -> None:
    repo = main_core.parents[2]
    if DEFAULT_SHM_PATH.exists():
        raise AssertionError(f"refusing to test while default shared memory exists: {DEFAULT_SHM_PATH}")
    default_signature = directory_signature(DEFAULT_RUNTIME_DIR)
    token = f"b0_runtime_{os.getpid()}_{uuid.uuid4().hex[:10]}"
    names = [f"/therapy_robot_{token}_a", f"/therapy_robot_{token}_b"]
    shm_paths = [Path("/dev/shm") / name[1:] for name in names]
    runtimes = [Path(f"/tmp/therapy_robot_{token}_a"), Path(f"/tmp/therapy_robot_{token}_b")]
    ports = [free_port(), free_port()]
    while ports[1] == ports[0]:
        ports[1] = free_port()
    owned_paths = set(shm_paths) | set(runtimes)
    processes: list[subprocess.Popen[str]] = []

    try:
        for name, runtime, port in zip(names, runtimes, ports):
            environment = os.environ.copy()
            environment.update(
                {
                    "THERAPY_ROBOT_SHM_NAME": name,
                    "THERAPY_ROBOT_RUNTIME_DIR": str(runtime),
                    "THERAPY_ROBOT_WEB_PORT": str(port),
                    "THERAPY_ROBOT_COLLISION_REQUIRED": "0",
                    "THERAPY_ROBOT_ROOT": str(repo),
                }
            )
            core = start_process(main_core, environment, repo)
            processes.append(core)
            wait_until((Path("/dev/shm") / name[1:]).exists, f"{name} creation")
            web = start_process(main_web, environment, repo)
            processes.append(web)
            wait_web(port, web)

        assert ports[0] != ports[1], "test ports unexpectedly collided"
        for instance_index, (port, runtime) in enumerate(zip(ports, runtimes)):
            assert "core_heartbeat_ms" in get_json(port, "/api/state")
            runtime.mkdir(parents=True, exist_ok=True)
            marker = runtime.name
            (runtime / "acupoint_sequence.log").write_text(marker, encoding="utf-8")
            (runtime / "acupoint_sequence.pid").write_text("99999999\n", encoding="ascii")
            expected_speed = "0.42" if instance_index == 0 else "0.77"
            post_json(port, "/api/speed", {"multiplier": float(expected_speed)})
            assert (runtime / "speed_multiplier").read_text(encoding="ascii").strip() == expected_speed
            status = get_json(port, "/api/acupoint_sequence/status")
            assert marker in status["log_tail"]
            assert status["log"] == str(runtime / "acupoint_sequence.log")

        post_json(ports[0], "/api/acupoint_sequence/stop")
        assert not (runtimes[0] / "acupoint_sequence.pid").exists()
        assert (runtimes[1] / "acupoint_sequence.pid").exists()

        registries = [
            [(processes[0].pid, "main_core"), (processes[1].pid, "main_web_control")],
            [(processes[2].pid, "main_core"), (processes[3].pid, "main_web_control")],
        ]
        write_process_registry(runtimes[0], registries[0])
        write_process_registry(runtimes[1], registries[1])
        kill_env = os.environ.copy()
        kill_env["THERAPY_ROBOT_RUNTIME_DIR"] = str(runtimes[0])
        result = subprocess.run([str(kill_script)], cwd=repo, env=kill_env, capture_output=True, text=True, timeout=4.0)
        assert result.returncode == 0, f"instance A kill failed: {result.stdout!r} {result.stderr!r}"
        wait_until(lambda: process_exited(processes[0]) and process_exited(processes[1]), "instance A stop")
        assert "core_heartbeat_ms" in get_json(ports[1], "/api/state"), "instance B was stopped by instance A cleanup"
        assert not (runtimes[0] / "processes.pid").exists()
        assert (runtimes[1] / "processes.pid").exists()

        kill_env["THERAPY_ROBOT_RUNTIME_DIR"] = str(runtimes[1])
        result = subprocess.run([str(kill_script)], cwd=repo, env=kill_env, capture_output=True, text=True, timeout=4.0)
        assert result.returncode == 0, f"instance B kill failed: {result.stdout!r} {result.stderr!r}"
        wait_until(lambda: process_exited(processes[2]) and process_exited(processes[3]), "instance B stop")
        assert not (runtimes[1] / "processes.pid").exists()

        verify_invalid_web_config(main_web, main_core, repo, token)
    finally:
        for process in processes:
            if process.poll() is None:
                stop_and_reap(process)
        for path in owned_paths:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    assert not DEFAULT_SHM_PATH.exists(), "runtime test created the default shared memory"
    assert directory_signature(DEFAULT_RUNTIME_DIR) == default_signature, (
        "runtime test modified the default runtime directory"
    )
    print("PASS: runtime, web ports, logs, PID registries and cleanup are isolated")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-core", required=True, type=Path)
    parser.add_argument("--main-web-control", required=True, type=Path)
    parser.add_argument("--kill-script", required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.main_core.resolve(), arguments.main_web_control.resolve(), arguments.kill_script.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
