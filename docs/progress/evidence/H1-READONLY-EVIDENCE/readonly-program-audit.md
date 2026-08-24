# 今晚 H1 只读程序静态审核

审核状态：`NOT_APPROVED_FOR_ENTITY_USE`

审核范围：`batch/h1-readonly-evidence` 当前 worktree 的源码和启动脚本。审核仅在 `zzqVM` (`x86_64`) 上完成，没有打开实体串口、没有启动机器人进程、没有访问 D405。

## 结论

当前分支没有可证明只读的实体采样程序，今晚不得直接运行当前 `main_motor` 或 `scripts/run-jetson-hardware.sh` 采集实体 H1 证据。

## 证据

- `src/motor/main_motor.cpp` 没有发现 `THERAPY_ROBOT_READ_ONLY`、`READ_ONLY` 或等价的总线写入守卫。
- `initialize_hardware()` 会打开配置的实体串口，并调用 `read_position()`、`read_brake()`；这些是读取请求，但程序随后仍进入完整硬件运行循环。
- 主循环包含 `enable_all()`、`stop_all()`、`zero_all_ram()`、`recover_arm_zero()` 和 `send_targets()` 路径。
- `stop_all()` 会调用停止、抱闸和 `motor_off`；文件末尾的退出路径直接调用 `stop_all(state, runtime, true, "shutdown")`。
- `enable_all()` 会调用 `motor_on()`、`set_position()` 和释放抱闸。
- `send_targets()` 会发送目标/轨迹；恢复路径还包含 arm-zero 和 jog 相关逻辑。
- `scripts/run-jetson-hardware.sh` 启动 `main_core`、`main_control`、`main_motor`、`main_sim`、`main_web_control` 和 `main_web_sim`，没有只读模式参数或只读退出保护。
- `scripts/b5_h1_preflight.py` 明确不打开串口，只能做软件预检，不能产生实体 K0-K4 样本。

## 禁止结论

在没有专用只读程序或经源码证明的只读分支前，不能把当前程序标为今晚可用，不能通过设置环境变量、关闭权限字段或选择默认模式来推断安全。

今晚如发现只能使用上述完整控制程序，必须停止补证并记录 `H1_BLOCKED`，不得继续打开实体串口。

```text
H1_CURRENT_STATUS=H1_EVIDENCE_INCOMPLETE
entity_motion_authorized=false
hardware_control_authorized=false
```
