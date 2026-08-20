# B6-EE-SIM：末端控制离线仿真器

任务 ID：`B6-EE-SIM`
基线：`659a1e51f0ef27c934ddbd1add177383eedfe92b`
分支：`batch/b6-ee-sim`
worktree：`/home/zzq/PTR/worktrees/b6-ee-sim`
状态：离线实现完成，待集成

## 输入和规则来源

仿真输入 `b6.ee-sim-input.v1` 包含完整的 `b6.end-effector-command.v1` 命令契约，
以及只属于仿真的侧别、故障场景、起点、安全高位和采样配置。命令必须通过合同字段、单位、
权限锁和 `contract_sha256` 校验；仿真信封另有 `input_sha256`。合同来自独立
`batch/b6-ee-contract` worktree 的 schema/示例，本任务未合并或修改该分支。

速度、分段时长、停止距离公式和 `emergency_stop`、`watchdog_timeout`、
`feedback_loss` 的安全停止事件直接调用 `scripts/b4_prep/m1_m2_motion_sim.py`。B6 只补充
三维末端几何、非接触偏移、工作空间/软限位、机箱边界和状态编排，不建立第二套运动故障规则。

## 运行

```bash
python3 scripts/b6_ee_sim.py \
  docs/progress/evidence/B6/EE-SIM/nominal-left-input.json \
  --out /tmp/b6-ee-left.json
```

正常状态为：

```text
IDLE -> SAFE_HIGH -> APPROACH -> HOLD -> RETRACT -> RETURN_HIGH -> COMPLETE
```

每个状态输出 `step`、`timestamp_ms`、`simulated_position_m`、
`simulated_velocity_m_s`、`distance_to_target_m`、`minimum_clearance_m` 和
`stopping_distance_m`。这些值是离线仿真事实，不是实体轨迹或电机目标。

## 约束和故障

- 合同最大速度 `0.05 m/s`、最大加速度 `0.20 m/s^2`。
- 停止距离使用 B4 的 `v^2/(2a)` 模型，并且不能超过非接触 approach offset 范数。
- 安全高位最低 `z=1.50 m`；保守离线工作空间 X `[-0.60,0.60]`、Y
  `[-0.60,1.50]`、Z `[0.20,1.80] m`。
- 机箱边界复用已审核范围 X `[-0.075,0.075]`、Y `[-0.100,0.650]`、Z
  `[-0.0125,0.7475] m`，全局 margin `0.001 m`。
- `operator_stop`、`emergency_stop`、`watchdog_timeout`、`feedback_loss`、
  `feedback_stale`、`collision_detected`、`soft_limit_violation` 进入 `STOPPED`。
- 输入/合同错误、停止距离不足、目标超界进入 `BLOCKED`，并将
  `simulation_valid=false`。

## 安全边界

所有输出固定：

```text
formal_use_allowed=false
execution_allowed=false
entity_action_authorized=false
nano_deployment_authorized=false
motor_command_generated=false
motor_target_generated=false
serial_payload_generated=false
```

仿真器不调用控制 API，不导入 serial/socket/requests，不写共享内存，不生成 G-code、
串口帧、关节目标或原生电机目标；不连接 Nano、串口、D405 或实体电机，不部署、不使能、
不回零、不置零，也不修改实体启动脚本。

## 验证

```bash
python3 -m unittest -v tests/test_b6_ee_sim.py
python3 -m py_compile scripts/b6_ee_sim.py tests/test_b6_ee_sim.py
git diff --check
```

证据位于 `docs/progress/evidence/B6/EE-SIM/`，包含左右正常、急停 `STOPPED`、目标越界
`BLOCKED`、完整测试日志和 SHA-256 清单。
