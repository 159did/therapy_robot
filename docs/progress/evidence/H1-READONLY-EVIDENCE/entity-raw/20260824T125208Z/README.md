# H1 entity read-only evidence

## Formal result

Conclusion: `H1_ENTITY_READONLY_PASS`.

This PASS is limited to direct K0-K4 feedback acquisition and the no-motion audit. It does not certify motion readiness or a general hardware safety attestation.

## Scope decision

The experiment was explicitly limited to observation with all motors disabled and no motion authorization.
A physical emergency-stop button without software readback, a hardware watchdog that is not present, and an unstarted control panel are outside this read-only pass criterion.
K1-K4 have no brake hardware and are recorded as `not_applicable`. Homed, zeroed, limit and collision states are out of scope because no motion was authorized.

Raw samples were not changed. The original 50 JSONL rows and action audit remain the source evidence.

## Recorded facts

- Real Nano: `jetsonorin@192.168.2.100`, hostname `ubuntu`, architecture `aarch64`.
- Controller network time is authoritative: `2026-08-24T12:52:08.080Z UTC`.
- 50 samples: K0-K4, 10 per axis.
- All axes online, fault-free, disabled, and at zero reported velocity.
- K0 logical position `43206 native`; logical height `3.00041666667 mm`.
- No control command or target was sent; no motion occurred; D405 was not accessed.
- Collector exited and all three serial ports were released.
- Nano current bin/config hashes match the H1 preflight backup snapshot.

Evidence files in this window are covered by `raw-sha256.txt`.
