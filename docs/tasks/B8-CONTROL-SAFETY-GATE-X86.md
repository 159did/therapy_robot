# B8-CONTROL-SAFETY-GATE-X86 task card

## Identity and boundaries

- Base: `main=9e0c4b925062b0a7c8fd2fa25fd985fe9798402b`
- Branch: `batch/b8-control-safety-gate-x86`
- Worktree: `/home/zzq/PTR/worktrees/b8-control-safety-gate-x86`
- `platform=x86_64_vm`
- `host=zzqVM`
- `nano_tested=false`
- `arm64_tested=false`
- `entity_hardware_tested=false`
- Formal H1 state: `H1_EVIDENCE_INCOMPLETE`

This task is software-only. It must not open an entity serial port, access a
D405, start a hardware service, deploy to Nano, enable/home/zero/jog/move a
motor, create a formal K0-K4 target, or change calibration/hardware data.

## Deliverable

Provide a single reusable, fail-closed C++ decision implementation and apply it
at every Web POST control entry, the endpoint-to-joint consumer, and the
hardware command/target consumer. Defaults must deny entity control. No API in
this task may provision a positive entity authorization.

## Central safety state

The shared state contains:

- `execution_allowed`
- `entity_action_authorized`
- `hardware_mode`
- `h1_status`
- `emergency_stop`
- `feedback_valid`
- `feedback_age_ms`
- `limit_state`
- `collision_state`
- `watchdog_state`
- `brake_state_known`
- `brake_engaged`
- `request_id`
- `authorization_id`
- `authorization_expiry`
- `input_units`
- `input_schema_valid`
- rejection reason/counters for Web and consumers

Adding the state changes the shared-memory ABI, so schema `version` is advanced
from 2 to 3. Mixed version processes must not share a segment; all test and
future deployment processes must be rebuilt together.

## Rejection reasons

Entity control rejects on any of:

- `hardware_control_mode_not_explicit`
- `h1_status_not_pass`
- `execution_not_allowed`
- `entity_action_not_authorized`
- `emergency_stop_active`
- `feedback_invalid`
- `feedback_expired`
- `watchdog_timeout`
- `limit_state_abnormal`
- `collision_state_abnormal`
- `brake_state_unknown`
- `authorization_expired`
- `request_id_missing`
- `authorization_id_missing`
- `authorization_id_mismatch`
- `input_non_finite`
- `input_units_missing`
- `input_units_wrong`
- `input_schema_invalid`
- `unknown_input_field`
- `missing_input_field`
- `unknown_control_action`

The acceptance symbol `H1_ENTITY_READONLY_PASS` appears only as the required
comparison value. B8 does not assign that value to defaults, fixtures, shared
state, or runtime configuration. The default remains
`H1_EVIDENCE_INCOMPLETE`.

## POST inventory and policy

### Entity-control gate (default denied)

- `/api/command/return_arm_zero`
- `/api/command/return_z_zero`
- `/api/command/targets`
- `/api/command/jog_axis`
- `/api/command/recovery_jog_axis`
- `/api/command/jog_axis_continuous`
- `/api/command/endpoint_jog`
- `/api/command/endpoint_target`
- `/api/mode/switch`
- `/api/motion_test/point`
- `/api/motion_test/sequence/start`
- `/api/acupoint_sequence/start`
- `/api/command/enable_all`
- `/api/command/recover_arm_zero`
- `/api/command/disable_all`
- `/api/command/set_zero`
- `/api/command/reset_emergency_stop`
- `/api/command/clear_faults`
- `/api/reconcile/apply`
- `/api/command/enable_limit_stop_recovery`
- `/api/command/disable_limit_stop_recovery`

### Simulation/read-only computation

- `/api/motion_test/simulate`: allowed only in `SIMULATION`.
- `/api/speed`: offline simulation setting, allowed only in `SIMULATION`.
- `/api/ik/check`: calculation only, allowed only in `SIMULATION`.

Every allowed offline result still declares or guarantees:

```text
execution_allowed=false
entity_action_authorized=false
motor_command_generated=false
motor_target_generated=false
serial_payload_generated=false
```

### Fail-safe stop exception

The following actions can only reduce risk and may run without movement
authorization:

- `/api/command/emergency_stop`
- `/api/command/stop_all`
- `/api/motion_test/sequence/stop`
- `/api/acupoint_sequence/stop`

This exception cannot create a target. `disable_all` is not exempt because it
was explicitly required to use the entity-control gate.

Any future unknown `/api/*` POST is rejected by the same global hook before a
route handler can execute.

## Consumers and scripts

- `main_control`: checks the same pure function before converting a new
  endpoint target into `target_command_seq`. SIMULATION permits only offline
  conversion; non-simulation requires the full entity gate.
- `main_motor`: checks the same pure function before hardware initialization
  (and therefore before any serial open), then again before consuming a command
  or target sequence. Command id 4 is the fail-safe stop exception. Unknown
  command ids are rejected.
- Shared-memory target/command writes in Web are behind the global hook.
- Hardware launch surfaces audited: `scripts/run-jetson-hardware.sh`,
  `scripts/switch-run-mode.sh`, `scripts/build-jetson.sh`, and
  `scripts/deploy-jetson.sh`. Their entity behavior is unchanged by B8.

## Tests and acceptance

- Pure C++ rejection/allowance and input-schema tests.
- Static coverage test proving all registered API POST routes are classified,
  Web has one global pre-request gate, and both downstream consumers recheck.
- Black-box isolated simulation API test proving all 15 required entity
  endpoints are uniformly rejected and command/target/motor state does not
  change.
- Existing GET/readiness/workflow/motion-plan isolation regressions.
- Full CTest, Python compile/unittest, repository safety scan and diff check.

Ready for review requires every scoped check to pass. It never means Nano,
ARM64, entity hardware, calibration, or movement readiness.

## Rollback

Before integration, remove the B8 commit or abandon the worktree/branch. After
integration, revert the single B8 commit with `git revert <B8-commit>`. Because
the shared-memory ABI changes to version 3, stop software-only test processes
and release only their explicitly isolated test shared-memory segments before
running an older build. Do not delete the default shared-memory segment while
an unrelated instance is active.
