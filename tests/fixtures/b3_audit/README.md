B3-D audit fixtures are synthetic/offline only. They must never contain entity
serial, D405, motor, or Nano data. The checked-in set supports deterministic
manual/report-browser checks; unit tests also create isolated variants in a
temporary directory for tampering and fail-closed cases.
