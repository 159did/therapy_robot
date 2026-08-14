# Git and Worktree Workflow

Updated: 2026-08-14
Repository: `/home/zzq/PTR/therapy_robot`

## Repository Boundary

Git is initialized only in the maintained `therapy_robot` project. Never initialize or stage `/home/zzq/PTR` as a whole; it contains toolchains, archives, virtual environments, historical projects, and machine-local evidence.

The initial baseline includes the completed P0 motion-test trajectory lock. Do not restore `backups/20260814-p0-batch1-before` over the baseline.

This repository is local-only until configuration, calibration, and history are reviewed for remote publication. Do not add a remote or push the repository as part of B0.

## Branches

`main` is the integration branch. Functional work is not edited directly on `main`.

Task branches use:

```text
batch/b0-infrastructure
batch/b1-auto-lock
batch/b1-offset
batch/b1-vision
batch/b1-frontend
```

Worktrees live outside the repository:

```text
/home/zzq/PTR/worktrees/b0-infrastructure
/home/zzq/PTR/worktrees/b1-auto-lock
/home/zzq/PTR/worktrees/b1-offset
/home/zzq/PTR/worktrees/b1-vision
/home/zzq/PTR/worktrees/b1-frontend
```

B1 worktrees are created only after G0 passes so they start from the integrated B0 commit.

Example after G0:

```bash
cd /home/zzq/PTR/therapy_robot
git branch batch/b1-auto-lock main
git worktree add /home/zzq/PTR/worktrees/b1-auto-lock batch/b1-auto-lock
```

## Ownership

During B1, one owner edits each hotspot:

```text
src/web/main_web.cpp                       1号
src/motor/main_motor.cpp                   2号
tests/test_hardware_emulator.py            2号
config/ and hardware scripts               2号
vision scripts and calibration fixtures    3号
web/                                       4号
CMakeLists.txt and shared-memory files      1号 integration lead
```

When a task needs a test owned by another task, add an independent test file or submit an interface request. Do not edit the other owner's hotspot in parallel.

## Commit Rules

Before committing:

```bash
git status --short
git diff --check
git diff
```

Each commit contains one task-sized change. Generated builds, logs, PID files, virtual environments, local offsets, and credentials are never staged. Use `git add -n` before the first real add of a new path.

Every task report records:

```text
baseline commit
actual files changed
test commands and return codes
x86 status
ARM64 status
Nano status
entity status
artifact SHA256
known failures
rollback commit or method
```

Software results must not be described as Nano deployment, real motor verification, or physical acceptance.

## Integration

The integration lead reviews and merges one task at a time. B1 merge order is:

```text
B1-B offset source
B1-A automatic-motion lock completion
B1-C vision baseline
B1-D safe frontend
G1 full software gate
```

After each merge, run the affected tests. Run the complete gate and ARM64 build only after all B1 tasks are integrated.

Do not force-remove a worktree with uncommitted changes. Inspect `git status`, preserve task evidence, then use normal `git worktree remove` only after integration or explicit abandonment.

## Hardware Boundary

Git operations, builds, and pseudo-terminal tests do not authorize Nano deployment, serial access, motor enable, zero capture, automatic motion, or human contact. Those remain separate, explicit operations with their own approval and physical checklist.
