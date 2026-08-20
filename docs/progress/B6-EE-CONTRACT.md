# B6-EE-CONTRACT 进度

基线：`659a1e51f0ef27c934ddbd1add177383eedfe92b2`
分支：`batch/b6-ee-contract`
工作树：`/home/zzq/PTR/worktrees/b6-ee-contract`
当前状态：实现和离线验证完成，待集成

## 完成情况

| 步骤 | 状态 | 证据 |
|---|---|---|
| 既有契约审核 | 完成 | 已审核 B2/B3/B4、B5-VISION、B5-DEMO、只读 API/状态、机箱碰撞边界和 K0-K4 软限位约定。 |
| 输入/输出 Schema | 完成 | Draft 2020-12，版本分别为 `b6.end-effector-command.v1` 和 `b6.end-effector-validation-result.v1`，未知字段关闭。 |
| 离线校验器 | 完成 | 严格单位、坐标系、有限数值、运动上限、工作空间、非接触偏移、安全锁与 SHA-256 校验。 |
| 正常/失败样本 | 完成 | 1 个正常样本和 7 个失败样本，覆盖缺字段、单位、坐标系、越界、权限、急停前置条件和哈希不匹配。 |
| 专项测试 | 完成 | 19 项通过，包括 Schema 自检、CLI、样本结果、候选坐标执行锁、未知/重复字段、非有限值、UTC 时间、实验运动上限、零偏移、偏移端点越界和硬件依赖扫描。 |
| 安全范围核对 | 完成 | 变更仅位于 `scripts/b6`、`tests/b6`、`docs/tasks`、`docs/progress`。 |

## 样本预期

| 文件 | 预期 |
|---|---|
| `valid-command.json` | `valid=true`，仍不可执行，不生成 motor target 或 serial payload。 |
| `missing-field.json` | `missing_fields:approach_offset_m`。 |
| `unit-error.json` | `max_speed_unit_invalid`。 |
| `coordinate-frame-error.json` | `coordinate_frame_invalid`。 |
| `workspace-out-of-bounds.json` | `position_z_outside_workspace`。 |
| `permission-unlock.json` | `execution_allowed_must_be_false`。 |
| `emergency-stop.json` | `STOPPED` 输入试图关闭急停清除前置条件，阻塞为 `emergency_stop_required_clear_must_be_true`。 |
| `hash-mismatch.json` | `contract_sha256_mismatch`。 |

## 安全结论

离线输出证据位于 `docs/progress/evidence/B6/EE-CONTRACT/valid-report.json` 和 `blocked-report.json`。正常报告为 `valid=true` 但仍固定 `executable=false`、`execution_allowed=false`；权限解锁样本报告为 `valid=false`、`blocking_reason=execution_allowed_must_be_false`。B6 专项 19 项与 B5 离线回归 28 项合计 47 项通过。

正常输入只代表契约可供离线仿真器读取，不代表 H1、碰撞检查、急停、反馈、正式外参或实体执行批准。候选视觉坐标不能设置 `executable=true`，所有输入和失败输出均保持 `formal_use_allowed=false`、`promotion_locked=true`、`execution_allowed=false`、`entity_action_authorized=false`、`nano_deployment_authorized=false`。

本任务未连接 Nano，未打开串口，未访问 D405，未部署，未使能、回零、置零或移动电机；未写共享内存，未生成轴角度、电机原生目标或串口 payload；未修改 B6-SAFETY-BASELINE、B6-EE-SIM、正式外参或实体控制文件。

这是仿真输入契约，不是实体电机命令。
