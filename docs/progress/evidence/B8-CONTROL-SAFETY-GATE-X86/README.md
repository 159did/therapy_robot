# B8 control safety gate evidence summary

```text
platform=x86_64_vm
host=zzqVM
nano_tested=false
arm64_tested=false
entity_hardware_tested=false
h1_status=H1_EVIDENCE_INCOMPLETE
base=9e0c4b925062b0a7c8fd2fa25fd985fe9798402b
branch=batch/b8-control-safety-gate-x86
```

## Results

| Check | Result |
| --- | --- |
| CMake configure | PASS |
| C++ build | PASS |
| CTest | PASS, 20/20 |
| Central pure safety gate | PASS |
| Static route/consumer integration | PASS |
| Black-box required entity API gate | PASS, 15/15 rejected by common gate |
| GET/failed-POST command, target, motor invariants | PASS |
| SIMULATION offline operation and entity output locks | PASS |
| Python `py_compile` | PASS |
| Python unittest | PASS, 87/87 |
| `git diff --check` | PASS |
| Repository safety scan | Completed read-only; publication remains blocked by baseline artifacts |

Raw logs in this directory:

- `platform-and-boundaries.log`
- `cmake-configure.log`
- `build.log`
- `ctest.log`
- `python-py-compile.log`
- `python-unittest.log`
- `git-diff-check.log`
- `repository-safety-scan.log`

## Coverage result

All entity endpoints named by B8 and all additional registered state-changing
POST endpoints found in `main_web.cpp` are centrally classified. Unknown API
POSTs default deny. The endpoint consumer, hardware initialization, hardware
command consumer, and hardware target consumer recheck the same pure function.
No scoped software control entry remains uncovered.

Hardware launch scripts were audited but their entity behavior was not changed.
There is deliberately no positive authorization writer/unlock API in B8. Future
integration must provide trusted, expiring authorization and live feedback,
watchdog, limit, collision and brake state without weakening defaults.

## No-hardware declaration

```text
entity_serial_accessed=false
d405_accessed=false
hardware_mode_started=false
run_jetson_hardware_started=false
motor_target_generated=false
motor_command_sent=false
motor_enabled=false
motor_disabled_command_sent=false
motor_homed=false
motor_zeroed=false
motor_jogged=false
motor_moved=false
formal_k0_k4_target_generated=false
calibration_modified=false
hardware_configuration_modified=false
```

Conclusion: `B8_SOFTWARE_READY_FOR_REVIEW`.
