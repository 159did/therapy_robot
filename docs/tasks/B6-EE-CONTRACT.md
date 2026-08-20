# B6-EE-CONTRACT 末端仿真输入契约任务卡

任务 ID：`B6-EE-CONTRACT`
基线：`659a1e51f0ef27c934ddbd1add177383eedfe92b2`
分支：`batch/b6-ee-contract`
工作树：`/home/zzq/PTR/worktrees/b6-ee-contract`
状态：离线实现完成，待集成

## 目标与边界

建立版本化的 `b6.end-effector-command.v1` JSON 契约，作为未来末端控制仿真器的只读输入；提供严格 JSON Schema、Python 离线校验器、正常/失败样本和回归测试。校验器只读取 JSON 并写入校验报告，不连接任何设备，也不产生执行数据。

这是仿真输入契约，不是实体电机命令。

本任务禁止连接 Nano、打开串口、访问 D405、部署、写共享内存、使能、回零、置零或控制电机；禁止生成电机轴角度、原生电机目标帧和串口 payload；不修改 B6-SAFETY-BASELINE、B6-EE-SIM、实体控制或正式外参文件。

## 已审核约定

| 来源 | 复用结论 |
|---|---|
| B2 `motion_plan` | 机器人基座坐标使用 `robot_base`，线性单位 `m`、角度单位 `rad`，路线需要碰撞检查；B6 不输出 B2 的关节 waypoint。 |
| B3 / B5-VISION | 未批准视觉变换使用 `robot_base_candidate`；大椎样例坐标为 `[0.1609163181992805, 0.1728330895391088, 1.2935009362530452] m`；候选坐标始终不可执行。 |
| B4 软件准备 | 权限字段失败关闭，非接触动作包含 approach/hold/retract，禁止 motor/joint/serial/shared-memory 输出。 |
| B5-DEMO | 状态序列复用 `APPROACH -> HOLD -> RETRACT -> RETURN_HIGH -> COMPLETE`，并保留 `STOPPED`、`BLOCKED`。 |
| 只读 API / 状态 | 已审核急停、限位报警、碰撞状态、endpoint target 状态和 simulation 状态字段；本任务不修改 API 或共享内存。 |
| 机箱碰撞 / 软限位 | 机箱模型为 `robot_base`、单位 `m`，槽位范围 X `[-0.075, 0.075]`、Y `[-0.100, 0.650]`、Z `[-0.0125, 0.7475]`，全局 margin `0.001 m`；K0-K4 软限位不转换成末端契约中的关节或电机目标。 |

## 输入契约

Schema 文件：`scripts/b6/end_effector_command.schema.json`。

| 类别 | 字段与约束 |
|---|---|
| 身份 | `command_id`、非负 `sequence`、UTC `created_at`、`source`、`idempotency_key`、规范化正文的 `contract_sha256`。 |
| 目标 | `coordinate_frame` 仅允许 `robot_base` / `robot_base_candidate`；`position_m` 为三个有限米值；使用 `orientation_policy`；`target_kind` 仅为离线仿真；`executable=false`。 |
| 运动限制 | `max_speed` 单位 `m/s` 且 `(0, 0.05]`；`max_acceleration` 单位 `m/s^2` 且 `(0, 0.20]`；jerk 固定为不支持；`timeout_ms` 为 `[1, 300000]`；approach/retract offset 单位为米。 |
| 安全锁 | `simulation_only=true`、`formal_use_allowed=false`、`promotion_locked=true`、`execution_allowed=false`、`entity_action_authorized=false`、`nano_deployment_authorized=false`、`h1_required=true`、`feedback_required=true`、`emergency_stop_required_clear=true`、`collision_check_required=true`。 |
| 状态 | `APPROACH`、`HOLD`、`RETRACT`、`RETURN_HIGH`、`STOPPED`、`BLOCKED`、`COMPLETE`。 |

`orientation_policy` 是方向策略名称，不是电机轴角度；v1 不携带关节角、轴角或驱动器原生目标。`max_jerk` 必须为 `{supported:false,value:null,unit:"unsupported"}`，避免伪造当前软件尚不支持的约束能力。

## 离线门限

校验器暂用保守末端工作空间 X `[-0.60, 0.60] m`、Y `[-0.60, 1.50] m`、Z `[0.20, 1.80] m`；approach/retract offset 的范数必须在 `[0.01, 0.20] m`，偏移后的端点也必须在该工作空间内。

这些数值仅用于当前离线契约测试，不是正式实体工作空间、碰撞模型、标定参数、软限位或运动许可。正式碰撞检查仍必须由后续独立安全实现完成；`collision_check_required=true` 只是不可解除的前置条件。

## 失败关闭规则

Schema 和 Python 校验器都拒绝未知字段、缺字段、错误单位和错误坐标系。CLI 解析层拒绝重复 JSON 键和 NaN/Infinity；Python 语义校验还拒绝负值或零速度/加速度、实验门限超限、目标或偏移端点越界、非接触偏移不足、安全锁解开、急停清除前置条件关闭和 SHA-256 不匹配。

任何失败均以退出码 `2` 输出 `valid=false` 及单一 `blocking_reason`，并固定：

```text
simulation_only=true
formal_use_allowed=false
promotion_locked=true
executable=false
execution_allowed=false
entity_action_authorized=false
nano_deployment_authorized=false
motor_target_generated=false
serial_payload_generated=false
```

## 文件与使用

- 输入 Schema：`scripts/b6/end_effector_command.schema.json`
- 结果 Schema：`scripts/b6/end_effector_validation_result.schema.json`
- 离线校验器：`scripts/b6/validate_end_effector_command.py`
- 可重复样本生成器：`scripts/b6/build_examples.py`
- 正常与失败样本：`docs/tasks/B6-EE-CONTRACT.examples/`
- 专项测试：`tests/b6/test_end_effector_command.py`

离线验证命令：

```bash
python3 scripts/b6/validate_end_effector_command.py \
  docs/tasks/B6-EE-CONTRACT.examples/valid-command.json \
  --out /tmp/b6-ee-valid-report.json
```

该命令只读取输入文件并写 JSON 报告；报告不是控制命令，不能发送给串口、电机或机器人服务。
