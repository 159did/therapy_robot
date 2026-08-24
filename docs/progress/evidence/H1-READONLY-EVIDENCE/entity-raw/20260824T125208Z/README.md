# H1 entity read-only evidence

Conclusion: `H1_EVIDENCE_INCOMPLETE`.

Controller network time: `2026-08-24T12:52:08.080Z` UTC; Nano wall clock is diagnostic only.

The real Nano was verified as `ubuntu`/`aarch64`. The standalone collector was compiled separately and ran against the three stable by-path serial ports. It collected 10 samples per axis (50 JSONL rows). It sent only position, status, state and K0 brake-read requests.

No enable, disable, stop, brake release, home, zero, jog, move, target or setpoint command was sent. No D405 was accessed and no motion occurred.

H1 remains incomplete because the Nano deployment directory has no Git metadata, binary-to-source provenance is not verified, and independent emergency-stop, watchdog, limit, collision, homed and zeroed states are not available from this read-only collector.
