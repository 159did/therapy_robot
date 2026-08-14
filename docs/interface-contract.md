# B0/B1 Interface Contract

This document freezes the software contracts at the B0 to B1 boundary. It describes what B1 work may consume without editing another owner's hotspot.

## Automatic Motion Lock

`POST /api/motion_test/sequence/start` is a backend hard lock. The response is HTTP `409` with these stable JSON fields:

```json
{
  "ok": false,
  "execution_locked": true,
  "error_code": "automatic_trajectory_locked",
  "motor_command_written": false,
  "motion_started": false
}
```

`GET /api/motion_test/sequence/status` exposes the same `execution_locked`, `error_code`, `motor_command_written`, and `motion_started` fields. `/api/motion_test/sequence/stop`, route preview, and simulation-only preview remain available. No environment variable, CLI flag, or frontend state is a valid bypass.

B1-A must preserve this contract while adding the symmetric lock to `/api/acupoint_sequence/start` and its direct CLI path.

## Shared Memory

`THERAPY_ROBOT_SHM_NAME` is optional. If unset, the exact legacy name remains `/therapy_robot_shared_state`. A configured name must start with `/`, be 2 to 255 bytes long, contain no second slash, and use only ASCII letters, digits, `_`, `-`, or `.` after the leading slash. `/.` and `/..` are rejected. Invalid input fails before `shm_open`.

`SharedState` layout and `version=2` are unchanged by B0. A task that changes the layout must increment the version and rerun all six target builds plus isolated tests.

## Runtime Resources

`THERAPY_ROBOT_RUNTIME_DIR` defaults to `/tmp/therapy_robot`. It must be a non-root absolute path with safe ASCII components. Web logs, sequence progress, sequence PID files, mode-switch logs, and speed files derive from this directory.

`THERAPY_ROBOT_WEB_PORT` defaults to `8080`; `THERAPY_ROBOT_SIM_WEB_PORT` defaults to `8081`. Both accept only decimal integers from 1 through 65535. Invalid values fail before listen.

Each managed process is recorded as:

```text
<pid> <proc-start-time> <expected-executable-name>
```

For a custom runtime directory, `kill-robot.sh` checks all three fields and stops only that registry. The legacy global pattern is retained only when the default directory has no registry, to migrate old unregistered instances.

`src/motor/main_motor.cpp` still reads the legacy default speed file and is owned by B1-B. B1-B must either consume `THERAPY_ROBOT_RUNTIME_DIR` or explicitly document why the hardware/simulation speed file remains shared.

## Ownership

| Area | Owner | Contract at B0 boundary |
|---|---|---|
| `src/web/main_web.cpp` | 1号/B1-A | Preserve motion-lock fields; add acupoint lock only in B1-A |
| `src/motor/main_motor.cpp` and hardware scripts | 2号/B1-B | Own offset source, startup fail-closed, and legacy speed-file adaptation |
| Vision/calibration scripts | 3号/B1-C | Offline-only fixtures and quality gates; no entity camera or motor access |
| `web/` and independent black-box checks | 4号/B1-D | Consume backend lock/status fields; do not recreate backend safety state |
| `CMakeLists.txt`, shared-memory files, B0 docs | 1号 | Integrate changes and run the unified gate |

## Gate Status

The default `validate-software.sh --lock-only` profile passes. The extended full PTY regression remains blocked by the known K4 positive soft-limit continuous-jog timeout. This is a software regression record, not a Nano or physical acceptance result.
