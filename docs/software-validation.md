# Software Validation

The maintained software-only validation entry is:

```bash
./scripts/validate-software.sh --lock-only
```

It never deploys to Jetson Nano and does not open physical serial devices. The pseudo-hardware stage creates its own PTYs and runs the existing `tests/test_hardware_emulator.py` unchanged.

## Default Gate

The default `--lock-only` profile runs:

1. `bash -n` for tracked shell scripts;
2. Python bytecode compilation for scripts and Python tests;
3. CMake configuration with `BUILD_TESTING=ON`;
4. all x86 build targets;
5. CTest, including shared-memory and runtime isolation tests;
6. the pseudo-hardware automatic-trajectory lock check;
7. a postflight check that the default shared-memory object is absent.

Every stage writes a log and exact return code to a timestamped directory under `build/validation-results/`. `MANIFEST_SHA256.txt` covers the metadata, summary and stage logs. The script returns nonzero when any required stage fails.

## Extended Regression

Run the complete existing pseudo-hardware motion regression with:

```bash
./scripts/validate-software.sh --full-emulator
```

This profile is expected to expose existing motion-regression failures rather than hide them. A failure in the known K4 continuous-jog soft-limit case must be reported as a failure until the owning task fixes and revalidates it.

Use `--skip-emulator` only for build-focused diagnostics. It is not sufficient for G0 or a safety gate.

## Reusing A Build

An existing isolated build directory can be reused:

```bash
./scripts/validate-software.sh --lock-only \
  --build-dir /home/zzq/PTR/worktrees/b0-infrastructure/build/b0-host
```

The emulator port can be changed when `18080` is unavailable:

```bash
./scripts/validate-software.sh --lock-only --port 18081
```

The entry refuses to start when `/dev/shm/therapy_robot_shared_state` already exists. This protects a running default-name instance from the emulator, which owns and removes that name during its isolated test.

## Boundaries

- Do not treat a passing PTY test as Nano deployment or physical motor acceptance.
- Do not run this entry while a default-name robot instance is active.
- The script does not modify `tests/test_hardware_emulator.py`.
- ARM64 build and Nano deployment remain separate, explicit gates.
