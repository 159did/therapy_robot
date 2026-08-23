# B7-SAFETY-GATE-INTEGRATION-SIM

## 目标

将 B6 集中式安全判定接入 B5 M1/M2 离线路线仿真入口。仿真请求必须先通过
`SIMULATION` 模式下的 `offline_simulation` 安全门，然后才能调用 B4 路线模型。

本任务只修改软件仿真和测试，不连接 Nano、串口或 D405，不启动硬件模式，不生成实体电机目标。

## 安全不变量

- 仿真使用 `SafetyState.default()`，模式固定为 `SIMULATION`。
- 仿真安全判定允许的是 `offline_simulation`，但 `execution_allowed` 始终为 `false`。
- `entity_control` 通过同一 B6 判定接口必须被拒绝，默认拒绝原因至少包含
  `hardware_control_mode_not_explicit` 和 `h1_status_not_pass`。
- 急停、看门狗超时和反馈丢失仍由底层 B4 模型注入，结果必须 `FAIL_CLOSED`、停止且不恢复。
- 输出记录 `safety_decision`，并保留 `entity_action_authorized=false`、`nano_deployment_authorized=false`。

## 修改范围

- `scripts/b5/m1_m2_route_sim.py`
- `tests/b5/test_m1_m2_route_sim.py`
- 本任务卡和进度记录

## 验证

```bash
python3 -m unittest -v tests/b5/test_m1_m2_route_sim.py
python3 -m unittest -v tests/b6/test_safety_baseline.py
python3 -m py_compile scripts/b5/m1_m2_route_sim.py tests/b5/test_m1_m2_route_sim.py
```

验收要求：左右名义路线和三类故障均先产生安全判定；实体控制默认拒绝；不访问实体设备。
