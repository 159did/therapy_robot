# B8 Agents 2/3/4 Integration Audit

Status: SOFTWARE_INTEGRATION_VERIFIED (x86_64 VM only)

This is the integration record for the first B8 deliveries. It is not an
entity-hardware acceptance record. H1 remains `H1_EVIDENCE_INCOMPLETE`.

The follow-up experiment entry points are documented in
`docs/EXPERIMENT-WORKFLOW.md`: `scripts/capture_d405.py` provides explicit
camera capture, and `scripts/experiment_workflow.py` produces the complete
offline state report while keeping hardware mode blocked until H1 and the
central gate are satisfied.

## Environment and boundaries

- Host: `zzqVM` at `192.168.216.129`
- Architecture: `x86_64` virtual machine
- Baseline main: `9e0c4b925062b0a7c8fd2fa25fd985fe9798402b`
- Integration branch: `integration/b8-agents-2-3-4`
- Integration worktree: `/home/zzq/PTR/worktrees/integration-b8-agents-2-3-4`
- Final integration commit: `74a186a9627e1443258eb364748b8d0ad8a7a9d9`
- Real Nano: not connected and not tested
- Entity serial: not opened or accessed
- D405/RealSense: not accessed
- Hardware service: not started
- `H1_STATUS`: `H1_EVIDENCE_INCOMPLETE`
- `entity_motion_authorized`: `false`
- `hardware_control_authorized`: `false`

The repository remains private because the historical baseline contains
machine-local hardware configuration and observation/calibration artifacts.
Those pre-existing artifacts were not deleted in this integration.

## Delivery identities and order

The three final delivery commits were identified from their named branches and
cherry-picked in dependency order:

1. Agent 3, `batch/b8-vm-software-acceptance`, `06e6f7ad3c1a6007202e4bcb404c7040ac931e3b`.
2. Agent 4, `batch/b8-low-speed-noncontact-prep`, `5045b5b537c8a7a10e64b3cded38ecfe59d0bd7a`.
3. Agent 2, `batch/b8-control-safety-gate-x86`, `846264d3a83c4f51faad319dc078df051fdfeadc`.

The resulting cherry-pick commits are recorded in
`evidence/B8-AGENTS-2-3-4-INTEGRATION/cherry-pick-order.txt`.

Agent 4's earlier base commit was `cb2abffa67e86187c580674ceb5a292365e7fdce`.
The final delivery commit restored the complete B8 low-speed preparation
package, including its progress document, evidence directory, checklist,
record example, offline preparation script, fixture builder, and test.

## Conflict resolution

Two modify/delete conflicts were caused by archival cleanup already present on
main. The latest delivery contents were retained:

- Agent 3: five B8 VM acceptance/progress/task/evidence files.
- Agent 4: `docs/tasks/B8-LOW-SPEED-NONCONTACT-PREP.md`.

No conflict remains on the integration branch. Agent 2 applied without a
conflict. Because Agent 4's final commit was a follow-up to its base package,
the complete package was restored by path from the verified
`batch/b8-low-speed-noncontact-prep` branch, including its evidence directory,
scripts, fixtures, and test. This restoration is recorded in the integration
commit rather than silently omitting the base delivery.

## Safety gate audit

Agent 2 adds the central `ControlSafetyGate` contract and applies it at three
boundaries: Web POST ingress, `main_control` target conversion, and
`main_motor` initialization/command consumption. Defaults are deny-by-default:

- `H1_EVIDENCE_INCOMPLETE`
- `execution_allowed=false`
- `entity_action_authorized=false`
- shared-memory ABI version 3
- unknown `/api/*` POST requests rejected

SIMULATION routes return computed/offline results only and report no entity
command or target generation. Fail-safe stop endpoints remain explicit
exceptions in the route inventory, but no such endpoint was called during this
audit. The hardware functions and serial paths remain source code for future
work; source presence is not evidence of execution.

The final route and shared-memory audits are stored under the integration
evidence directory.

## Verification

- CMake configure/build: PASS
- CTest: 20/20 PASS
- Python `py_compile`: PASS
- Python unittest: 96/96 PASS (including Agent 4 B8 protocol test 9/9)
- `git diff --check`: PASS
- Repository safety scan: read-only scan PASS; publication-blocking findings
  are historical (`captured_back_sample`, entity calibration/observation,
  machine-local hardware config)

No Nano, entity serial port, D405, motor enable, disable, homing, zeroing,
jogging, motion, brake release, or target command was used.

## Merge and rollback

This branch is ready for a non-fast-forward merge after the final clean-tree
check. Before merging, create a `backup/main-before-b8-agents-2-3-4-*` branch.
Rollback after merge is a normal `git revert` of the merge commit; do not use
reset or force-push. Main must not be treated as H1-passed by this integration.
