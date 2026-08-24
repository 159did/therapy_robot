# Five-axis entity read-only pose verification

Status: PASS
Nano: jetsonorin@192.168.2.100 (ubuntu)
Samples: 10 consecutive K0-K4 snapshots.
Entity serial accessed: yes, read-only position/status/brake feedback.
Motor enable: no. Brake release: no. Stop/zero/target/jog/move: no.
Motion: no. D405 accessed: no.
Build: Nano Debug build succeeded. Only future-timestamp warnings were emitted because Nano clock is behind the source timestamps.
Read-only mode: THERAPY_ROBOT_READ_ONLY=1; shared-memory commands were ignored; no target was sent; shutdown did not call stop/brake/motor-off.
Command snapshot: command_seq=0, command_id=0, target_command_seq=1 for all samples.
K0: raw=16057, logical=43206 native, height=3.0004167 mm, source=k0_persisted_session, coordinate_valid=1, brake_state_known=1, brake_engaged=1.
K1: raw=-4197, logical=422 native, source=fixed_offset_file.
K2: raw=-107083, logical=-249 native, source=fixed_offset_file.
K3: raw=4145, logical=-6 native, source=fixed_offset_file.
K4: raw=1018, logical=-1258 native, source=fixed_offset_file.
All axes were disabled, fault=0, feedback_error_state=0, coordinate_valid=1.
Serial ports were released after SIGTERM shutdown; no ttyUSB process remained.
Failure reason: none.

report.json is the structured result, samples.jsonl contains the ten snapshots, and commands.log records the session lifecycle.
