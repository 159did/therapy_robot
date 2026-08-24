# B8-LOW-SPEED-NONCONTACT-GO-NOGO

## GO 判定

定义：

```text
GO = AND(
  H1_ENTITY_READONLY_PASS,
  B8_SAFETY_GATE_PASS,
  REAL_NANO_ARM64_BUILD_PASS,
  NANO_READONLY_STATE_PASS,
  ESTOP_AVAILABLE,
  WATCHDOG_OK,
  FEEDBACK_VALID,
  SOFT_LIMITS_CLEAR,
  COLLISION_CLEAR,
  BRAKE_STATE_KNOWN,
  USER_APPROVED_SPECIFIC_ACTION,
  SINGLE_EXECUTION_AGENT,
  WORKSPACE_EMPTY,
  OPERATOR_PRESENT,
  ESTOP_LEAD_PRESENT
)
```

所有条件必须为真。GO 只允许未来一次单轴、一个离散动作的非接触窗口，不授权连续 jog、自动序列、左右完整路线、穴位序列或接触动作。

## 当前 NO-GO 判定

当前强制为：

```text
platform=x86_64_vm
simulation_only=true
nano_tested=false
arm64_tested=false
entity_experiment=not_run
hardware_authorized=false
entity_motion_authorized=false
H1_STATUS=H1_ENTITY_READONLY_PASS
B8_STATUS=PREPARATION_ONLY
RESULT=NO-GO
```

当前 NO-GO 至少因为 H1 实体只读证据不完整、真实 Nano 未测试、ARM64 未测试、Nano 只读状态未验证和具体动作未获用户批准。不能用 x86 编译或软件仿真替代这些条件。

## NO-GO 触发器

任一触发器立即 NO-GO：

- H1 不是 `H1_ENTITY_READONLY_PASS`；
- B8 安全门未集成或未通过；
- Nano 非真实 ARM64 或身份不匹配；
- 急停不可用；
- 看门狗异常；
- 反馈丢失或过期；
- 软限位未知、矛盾或异常；
- 碰撞配置缺失、未启用或报警；
- 抱闸未知或异常；
- 用户批准不对应本次 `request_id` 和单步动作；
- 单一执行代理、操作者或独立急停负责人缺席；
- 工作空间有人；
- 任何连续 jog、自动序列、目标队列或恢复重试意图；
- 任何接触人体、假人或其他物体的计划；
- 任意非只读请求、证据保存失败或参数不是批准后的明确值。

## 停止和恢复

异常发生时立即停止并保留原始状态；不得自动恢复、自动重试或沿用旧 request。恢复必须新建 `request_id`、重新获得明确授权、重新确认角色和工作空间、重新读取全部安全门，并重新从 GO 条件开始。

## 占位规则

以下值在未来批准前必须保持原样：

```text
axis=PLACEHOLDER_REQUIRES_APPROVAL
direction=PLACEHOLDER_REQUIRES_APPROVAL
speed=PLACEHOLDER_REQUIRES_APPROVAL
displacement=PLACEHOLDER_REQUIRES_APPROVAL
stop_distance_limit=PLACEHOLDER_REQUIRES_APPROVAL
```

任何将占位符替换为真实动作参数的变更都属于新的审批范围，不得在本准备分支中完成。


当前仍为 NO-GO：H1 只读 PASS 不会自动打开实体运动授权。
