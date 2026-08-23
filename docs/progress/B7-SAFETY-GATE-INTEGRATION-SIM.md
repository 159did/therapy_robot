# B7-SAFETY-GATE-INTEGRATION-SIM 进度

任务：将 B6 安全门接入 B5 M1/M2 离线仿真入口
分支：`batch/b7-safety-gate-integration-sim`
工作区：`/home/zzq/PTR/worktrees/b7-safety-gate-integration-sim`
状态：完成，待集成

## 执行步骤

| 步骤 | 内容 | 状态 | 证据 |
|---|---|---|---|
| B7-01 | 从当前 main 创建独立分支和 worktree | 完成 | Git worktree 状态 |
| B7-02 | 仿真入口调用 B6 `offline_simulation` 安全门 | 完成 | `scripts/b5/m1_m2_route_sim.py` |
| B7-03 | 记录安全判定并保留故障 fail-closed 仿真 | 完成 | `tests/b5/test_m1_m2_route_sim.py` |
| B7-04 | 运行定向测试、Python 编译和依赖扫描 | 完成 | `evidence/B7-SAFETY-GATE-INTEGRATION-SIM/` |
| B7-05 | 提交并交付集成信息 | 待执行 | commit id |

## 测试结果

```text
B5 路线定向测试：8/8 通过
B6 安全基线定向测试：16/16 通过
全量 Python unittest：76/76 通过
全量 Python py_compile：通过
git diff --check：通过
```

新增验证包括：左右名义路线和三类故障先通过 `offline_simulation` 安全门；
同一 B6 判定接口对默认 `entity_control` 请求保持拒绝，并返回
`hardware_control_mode_not_explicit`、`h1_status_not_pass` 等原因。

证据目录：

```text
docs/progress/evidence/B7-SAFETY-GATE-INTEGRATION-SIM/
```

本批次没有启动仿真服务，因此没有创建机器人进程、端口监听或共享内存。

## 硬件边界

本任务不访问 Nano 运行服务、实体串口、D405 或电机控制入口；不运行
`scripts/run-jetson-hardware.sh`，不执行 enable、home、zero、jog、move 或 target。
