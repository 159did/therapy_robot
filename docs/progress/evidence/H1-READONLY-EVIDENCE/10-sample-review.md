# H1 既有 10 次 K0 原始采样整理

状态：`REVIEW_ONLY_NOT_PASS`

本文件是对既有原始文件的派生整理，不修改原始文件。原始采样仍保存在：

```text
docs/progress/evidence/H1-READONLY-EVIDENCE/entity-raw/pose-readout-19700101T023629Z-retry1/samples.jsonl
```

原始 `samples.jsonl` SHA-256：

```text
8e34f4162f6f189ce9e1ff84252be311ded033593aadc948e8164c78ca4df984
```

## K0 采样摘要

所有 K0 行的静态反馈值均为：

```text
feedback_position_native = 16057
coordinate_offset_native = -27149
actual_motor_native = 43206
actual_axis_si = 0.00300042
coordinate_source = k0_persisted_session
coordinate_valid = 1
online = 1
enabled = 0
fault = 0
feedback_error_state = 0
brake_state_known = 1
brake_engaged = 1
actual_motor_native_velocity = 0
```

| 样本 | snapshot_time_ms | feedback_sequence | feedback_time_ms | feedback_age_ms |
|---:|---:|---:|---:|---:|
| 1 | 9857121 | 42 | 9857081 | 40 |
| 2 | 9857221 | 44 | 9857159 | 62 |
| 3 | 9857321 | 45 | 9857261 | 60 |
| 4 | 9857421 | 47 | 9857402 | 19 |
| 5 | 9857522 | 48 | 9857473 | 49 |
| 6 | 9857622 | 50 | 9857615 | 7 |
| 7 | 9857722 | 51 | 9857686 | 36 |
| 8 | 9857822 | 52 | 9857758 | 64 |
| 9 | 9857922 | 53 | 9857900 | 23 |
| 10 | 9858023 | 54 | 9857971 | 52 |

字段单位只按原始字段名解释：`*_ms` 为毫秒，`*_native` 为驱动器 native 计数，`actual_axis_si` 为 SI 值。`snapshot_time_ms` 和 `feedback_time_ms` 没有绝对墙上时钟或时区，因此不能作为检查日期。

这 10 次采样可以作为“已有原始 K0 反馈记录”，但不能单独升级为 `H1_ENTITY_READONLY_PASS`。实体身份、操作者、绝对检查时间、实际串口路径、软限位、急停和看门狗仍需今晚补采。
