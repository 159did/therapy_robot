# B5-H1 Saturday Nano Preflight

Status: software/document preparation only; Nano, serial, D405, and motors were not accessed.

Baseline: `0e65a84e66b9c78d24ee1d5af07a10df679e6c8d`

This checklist is for the first physical H1 read-only window. It confirms device identity, serial availability, and trustworthy K0 feedback. It does not authorize motion.

## Window boundary

Allowed: record the software commit, device identity, serial occupancy, firmware/device status, K0 position and limits, feedback quality, and timestamps.

Forbidden: any write frame or motion target; enable, home, zero, jog, speed/limit/offset changes, brake writes, Nano deployment, D405 access, entity target generation, or human contact. If an action cannot be proven read-only, mark `BLOCKED` and stop.

## A. Paper confirmation before start

- [ ] Device model, Nano instance, serial path, and expected firmware are filled in.
- [ ] Operator, emergency-stop/power-off owner, and recorder are identified.
- [ ] No person is touching the arm; end effector is clear; emergency stop and power-off are reachable.
- [ ] Approved software commit matches the worktree and the worktree is clean.
- [ ] Scope is only `H1` and `K0_READ_ONLY`.
- [ ] Evidence files can be saved; save failure stops the window.

## B. Software preflight (without the device)

- [ ] Run the existing software preflight and save output; do not start an entity driver.
- [ ] Use `GET /api/readiness/attestation` only for software readiness. Confirm `authorization_scope=software_precheck_only`, `execution_allowed=false`, `entity_action_authorized=false`, and `nano_deployment_authorized=false`.
- [ ] Do not start `run-jetson-hardware.sh`, jog/enable paths in `test_single_axis.py`, or any serial writer.
- [ ] Save commit, preflight time, and output hash.

## C. Device identity (still read-only)

1. Record device path, USB VID/PID, serial number, firmware version, and Nano hostname.
2. Compare each field with the approved identity.
3. Missing, conflicting, or unreadable identity means `BLOCKED`; do not try a movement.
4. Identity is evidence only; do not write device, udev, configuration, or firmware.

## D. Serial occupancy (read-only)

- [ ] Record device path and check time.
- [ ] Record `free`, `occupied`, or `unknown`.
- [ ] If occupied, record process name/PID; do not kill, restart, or take over the port.
- [ ] `occupied` or `unknown` means `BLOCKED`.
- [ ] Continue only after the responsible person confirms the port is free.

## E. K0 read-only state samples

Collect state only; do not send stop, enable, brake, or target commands. Each sample records K0 position/height and unit, velocity and unit, lower/upper soft limits and unit, brake state (`engaged`, `released`, or `unknown`), feedback quality (`valid`, `degraded`, or `lost`), feedback age, monotonic timestamp, sequence, and device fault/alarm state.

Save at least three consecutive samples. Sequence and monotonic timestamps must increase; feedback must be current. Do not send a command to make it “stable”. Existing offline field names are `height`, `velocity`, `brake_state`, `feedback_quality`, `feedback_age_ms`, and `stop_state`. Entity records must state `synthetic=false` and must not reuse offline fixtures as entity readings.

## F. Result rule

Write `PASS` only when identity matches, the serial port is free, K0 height/limits/brake/feedback are explainable, consecutive samples have no loss/time reversal/limit violation/contradiction, no forbidden action occurred, and evidence is saved. Otherwise write `BLOCKED` with the first blocking reason. H1 `PASS` only permits a separate request for a low-speed short-distance test; it does not authorize motion.

## G. Immediate stop conditions

Stop on identity mismatch, occupied serial, lost or stale feedback, unstable position/velocity, unknown or contradictory brake state, unknown limits, clock reversal, any write request, unreachable emergency stop, person entering the area, or evidence failure.

## Forbidden intent keywords for review

`enable`, `disable`, `home`, `zero`, `jog`, `move`, `target`, `setpoint`, `brake release`, `write`, `calibrate`, `offset`, `deploy`, `camera open`.

## Deliverables

- `B5-H1-SATURDAY-RECORD.json`: facts and samples;
- `B5-H1-SATURDAY-RESULT.md`: `PASS` or `BLOCKED` and reason;
- raw software preflight, identity, and occupancy outputs with hashes.
