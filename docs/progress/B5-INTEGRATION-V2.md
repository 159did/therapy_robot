# B5 offline integration v2 progress

Baseline: `4190449094e1ccf7832a2a0889049818f97bff05`
Branch: `integration/b5-offline-v2`
Worktree: `/home/zzq/PTR/worktrees/b5-offline-integration-v2`

## Integrated change

Source branch: `batch/b5-demo`
Source commit: `8ff8282440f39830f9b61d4db4b8fe072e640e12`
Source parent: `f8957a4356c6cc589c4c43204016ea2700bc5ab1`
Merge commit: `79de69d`

The new adapter reads the real offline JSON contracts produced by B5-M1/M2 and B5-VISION and feeds a locked, simulation-only DEMO report. It validates schema, route side, state sequence, input hashes, quality, candidate targets, permission fields, and hardware-access flags.

## Verification

- DEMO flow, adapter, M1/M2 route, and B4 motion tests: 27 PASS.
- VISION, calibration, D405 quality gate, and paper-results tests: 30 PASS.
- B4 offline discovery: 31 PASS.
- B5 offline discovery: 6 PASS.
- Python compilation and `git diff --check`: PASS.

## Boundary

This remains offline-only. No Nano, serial port, D405 device, shared memory, deployment, motor enable, homing, zeroing, or motion command was used.

The adapter output is a candidate end-effector position for simulation and remains non-executable. H1 entity read-only is still pending Nano availability and an explicitly scheduled physical test.
