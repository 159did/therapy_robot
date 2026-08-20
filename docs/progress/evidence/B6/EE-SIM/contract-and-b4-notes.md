# B6-EE-SIM 输入和规则读取证据

## B6-EE-CONTRACT

只读来源：`/home/zzq/PTR/worktrees/b6-ee-contract`，分支 `batch/b6-ee-contract`，基线
`659a1e51f0ef27c934ddbd1add177383eedfe92b`。读取了：

- `docs/tasks/B6-EE-CONTRACT.md`
- `scripts/b6/end_effector_command.schema.json`
- `scripts/b6/validate_end_effector_command.py`
- `docs/tasks/B6-EE-CONTRACT.examples/valid-command.json`
- `tests/b6/test_end_effector_command.py`

绑定结论：使用 schema `b6.end-effector-command.v1`；保留完整合同 SHA-256、安全锁、米制
速度/加速度、非接触 approach/retract offset 和候选坐标不可执行语义。不猜字段、不复制
合同代码、不合并或修改合同分支。

## B4 运动模型

只读并运行基线中的 `scripts/b4_prep/m1_m2_motion_sim.py`，工具版本 `b4-prep-c.1`。
B6 调用其 `finite()` 和 `simulate()`，复用：

- 分段时长 `ceil(distance/speed*1000)`；
- 停止距离 `speed^2/(2*stop_deceleration)`；
- `emergency_stop`、`watchdog_timeout`、`feedback_loss` 的 fail-closed 事件链。

B6 自己只负责末端三维坐标、工作空间/软限位、非接触偏移、机箱碰撞间隙与状态名称。
零位移段显式输出 0 时长/0 速度/0 停止距离，因为 B4 的动作输入只接受正位移，而 B6 起点
允许已经处于 `SAFE_HIGH`；实际运动段全部通过 B4 计算。
