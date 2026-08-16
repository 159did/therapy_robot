# B0-B3 Interface Contract

This document freezes the software contracts from B0 through B3. It describes
what each workstream may consume without editing another owner's hotspot or
weakening an earlier safety boundary.

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

The historical paragraph above records the B0 boundary. G1 later passed on
`main=e6689d2`; the K4 regression was fixed before that gate. B2 starts from
the B2 preparation commit recorded in the task cards and does not relax any
B1 lock.

## B2 Read-Only Workflow Contract

B2 adds exactly three read-only endpoints:

```text
GET /api/workflow/state
GET /api/workflow/self_check
GET /api/motion_plan/preview?side=left|right
```

No B2 endpoint accepts `POST`, writes shared state, increments a sequence,
starts a process, creates a PID file, opens a serial device, or changes a
motor target. Every HTTP response, including HTTP 400/409/500 responses,
contains these stable fields:

```json
{
  "schema_version": "b2.v1",
  "ok": true,
  "motor_command_written": false,
  "source_state": {
    "command_seq": 0,
    "target_command_seq": 0,
    "endpoint_target_seq": 0
  },
  "blocking_reasons": []
}
```

`blocking_reasons` is an array of objects. Each object contains stable string
fields `code`, `source`, `severity`, and `message`. `severity` is one of
`info`, `warning`, or `blocking`. Clients make no safety decision from
`message`; `code` is the machine-readable value. Unknown fields are ignored.
Missing stable fields, a schema version other than `b2.v1`, or a network
failure must be treated by the frontend as blocked.

### Workflow State

`GET /api/workflow/state` additionally contains:

```json
{
  "workflow_state": "storage",
  "allowed_actions": ["view_state", "view_self_check", "preview_motion_plan"],
  "self_check_summary": {
    "status": "blocked",
    "passed": 0,
    "failed": 1,
    "unknown": 0
  },
  "plan_id": null,
  "plan_hash": null,
  "execution_locked": true
}
```

`workflow_state` is one of `offline`, `fault`, `locked`, `storage`,
`standby`, `vision_blocked`, `ready_for_preview`, or `preview_blocked`.
`allowed_actions` may contain only `view_state`, `view_self_check`,
`refresh_state`, and `preview_motion_plan`. B2 never returns an execute,
enable, home, jog, capture, deploy, or treatment action. Unknown or
inconsistent input state maps to a blocked state, never to
`ready_for_preview`.

### Self Check

`GET /api/workflow/self_check` additionally contains `self_check_summary` and
a `checks` array. Each check contains:

```json
{
  "id": "collision_config",
  "status": "pass",
  "blocking": true,
  "reason_code": null,
  "observed": "configured_enabled_required"
}
```

`status` is `pass`, `fail`, or `unknown`. B2 reads only already-available
state and files. It does not probe serial ports, connect a camera, release a
brake, enable an axis, capture a software zero, or generate calibration.
Missing formal camera extrinsics and unverified entity offsets remain
blocking facts, even when synthetic fixtures are used by tests.

### Motion Plan Preview

`GET /api/motion_plan/preview` accepts exactly one `side` value, `left` or
`right`. Missing, duplicate, or unsupported values return HTTP 400 with the
common fields and `error_code=invalid_motion_plan_side`. A valid request
additionally contains:

```json
{
  "plan_id": "b2-0123456789abcdef",
  "plan_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "preview_valid": false,
  "execution_allowed": false,
  "plan": {
    "schema_version": "b2.motion-plan.v1",
    "side": "left",
    "coordinate_frame": "robot_base",
    "units": {"linear": "m", "angular": "rad"},
    "segments": []
  }
}
```

The plan object is immutable after construction. Its canonical form is UTF-8
JSON with object keys sorted lexicographically, no insignificant whitespace,
JSON booleans/null in lowercase, and finite numbers rendered by the
implementation's documented round-trip representation. `plan_hash` is
`sha256:` followed by the lowercase SHA-256 of that canonical plan object.
`plan_id` is `b2-` followed by the first 16 hash hex digits. Timestamps,
source-state sequence values, diagnostics, `plan_id`, and `plan_hash` are not
part of the hashed object. The same inputs produce the same ID and hash; any
plan input change must produce both a new ID and a new hash.

Each segment has a stable `segment_id`, `phase`, start and target waypoint,
and a `preflight` object containing `ok`, `collision_checked`, `reason_code`,
`collision_link`, `collision_obstacle`, and `path_fraction`. A rejected plan
identifies the first rejected segment and preserves all segment diagnostics.
The plan model has no motor-write or shared-memory-write interface.

B2 contains no measured production route heights. Synthetic route fixtures
must be labelled `formal_use_allowed=false`. Without verified production
parameters, formal camera extrinsics, and all required preflight inputs, the
response remains `preview_valid=false`, `execution_allowed=false`, and
includes a blocking reason. `execution_allowed` is fixed false throughout
B2 and G2, including for a collision-clear synthetic plan.

### Read-Only Invariants

Tests snapshot these values before and after repeated and concurrent calls:

```text
SharedState.command.command_seq
SharedState.command.target_command_seq
SharedState.control.endpoint_target.target_seq
all configured motor enabled flags and target_native values
automatic-sequence PID/progress files
pseudo-bus action command counts
```

All values and files remain unchanged. Tests use an isolated shared-memory
name, runtime directory, Web port, offline vision fixtures, and PTY pseudo
hardware only. They never use Nano, an entity serial port, or an entity
camera. The B1 automatic-trajectory HTTP 409 contract remains active and is
retested at G2.

## B3 Entity-Preparation Read-Only Contract

B3 produces only software-readiness facts, a pure-simulation K0 preparation
trace, offline camera-extrinsics candidate packages, and audit reports. It
does not issue a motor-control authorization or a token consumable by a
control path. It does not deploy Nano, connect an entity serial device or
entity D405, enable or zero an axis, release a brake, or move a motor.

B1 automatic-motion locks and all three B2 GET contracts remain unchanged.
Every B3 result contains these stable values:

```text
motor_command_written=false
execution_allowed=false
entity_action_authorized=false
nano_deployment_authorized=false
```

Consumers may ignore unknown fields. A missing stable field, unknown schema,
type mismatch, clock rollback, corrupt input, or network failure is treated
as blocked. No B3 output represents an entity-executable state.

### Readiness Attestation

B3 adds exactly one network endpoint:

```text
GET /api/readiness/attestation
```

Its response uses `schema_version=b3.v1` and contains at least:

```text
ok
motor_command_written=false
execution_allowed=false
entity_action_authorized=false
nano_deployment_authorized=false
authorization_scope=software_precheck_only
attestation_id
issued_at_ms
expires_at_ms
source_state.command_seq
source_state.target_command_seq
source_state.endpoint_target_seq
source_fingerprint
software_commit
config_hashes
checks[]
blocking_reasons[]
```

The lifetime is at most 300 seconds and is computed from an injected clock in
the pure model. The attestation binds the software commit, the three source
sequence values, emergency-stop, collision and recovery facts, and all named
configuration hashes. Any bound-source change, expiration, clock rollback,
unknown value, or corrupt value invalidates verification. A fixed clock and
identical inputs produce the same `attestation_id`.

This object is a snapshot of software preconditions, not a capability token.
No existing or new POST endpoint, CLI command, shared-memory command, or motor
path may accept it to unlock a B1 control path.

### K0 Preparation-Height Simulation

The pure-simulation result uses
`schema_version=b3.k0-prepare-sim.v1`. It includes synthetic parameters, the
state trace, operator-confirmation points, stop reasons, feedback, brake and
watchdog facts, a final safe state, and stable reason codes.

Heights, speeds, and stopping distances are normalized or explicitly marked
`synthetic`. B3 defines no production K0 preparation height, native motor
target, or entity offset. The model exposes intent and state only; it has no
shared-memory, motor-driver, serial, or execution function.

### Camera-Extrinsics Candidate Package

The package uses `schema_version=b3.camera-extrinsics-candidate.v1`. It
contains a candidate ID, fit-input hashes, independent-validation input
hashes, the candidate matrix, units and coordinate frames, quality metrics,
thresholds, tool versions, and blocking reasons. The fit and validation data
sets must be provably disjoint.

Even when every offline check passes, the package contains:

```text
formal_use_allowed=false
promotion_locked=true
execution_allowed=false
```

B3 does not write `calibration/camera_to_base.json` and does not relabel a
fixture as formal data. Entity capture and formal promotion require a later,
separately authorized V2/B4 window.

### Audit Report

The report uses `schema_version=b3.audit-report.v1`. It contains the source
commit, build-artifact hashes, configuration and input hashes, readiness,
K0-simulation and camera-candidate summaries, an event hash chain, test
results, and entity-access declarations.

The report generator reads only explicit inputs and writes only a
user-selected output directory. Identical inputs produce an identical core
report. A missing item, hash mismatch, event-order error, or broken chain
returns nonzero and marks the report invalid. The frontend only displays the
report and readiness facts; it does not create or modify an authorization or
send a control POST.

### G3 Invariants

- Both B1 automatic APIs and both direct CLIs remain locked.
- B2 and B3 GET requests do not change shared state, motor targets,
  PID/progress files, or pseudo-bus action counts.
- Missing formal extrinsics, production K0 height, entity offsets, or Nano
  configuration remains a blocking fact.
- x86, CTest, full PTY, Web/API, offline-vision, syntax, and ARM64 software
  gates must all pass before a B4 entity window can be requested.
- Passing G3 does not grant any B4 authorization.
