# B6-EE-SIM 进度

基线：`659a1e51f0ef27c934ddbd1add177383eedfe92b`
分支：`batch/b6-ee-sim`
worktree：`/home/zzq/PTR/worktrees/b6-ee-sim`
状态：待集成（纯软件离线仿真）

| 编号 | 状态 | 证据 |
|---|---|---|
| EE-SIM-01 核对基线并建立独立分支/worktree | 已完成 | `baseline.txt` |
| EE-SIM-02 读取 B6-EE-CONTRACT schema/示例 | 已完成 | `contract-and-b4-notes.md` |
| EE-SIM-03 复用 B4 运动和故障模型 | 已完成 | `scripts/b6_ee_sim.py`、输出 `safety_model` |
| EE-SIM-04 实现合同适配、三维轨迹和状态机 | 已完成 | `scripts/b6_ee_sim.py` |
| EE-SIM-05 左右正常、STOPPED、BLOCKED 示例 | 已完成 | `nominal-*.json`、`emergency-stop.json`、`target-out-of-workspace.json` |
| EE-SIM-06 约束、故障、确定性和安全测试 | 已完成 | `tests/test_b6_ee_sim.py`、`verification.txt` |
| EE-SIM-07 依赖扫描和交付审查 | 已完成 | `dependency-scan.txt`、`sha256.txt` |

## 结果摘要

- 左侧：`b6-ee-sim-730ad7341a70bc63f2f4a34a`，`simulation_valid=true`，
  `final_state=COMPLETE`。
- 右侧：`b6-ee-sim-a743ea92f16c48ed1a011446`，`simulation_valid=true`，
  `final_state=COMPLETE`。
- 急停：`simulation_valid=true`，B4 事件链为
  `stop_requested -> stopping -> stopped`，`final_state=STOPPED`。
- 目标超界：`simulation_valid=false`，`blocking_reasons=[target_out_of_workspace]`，
  `final_state=BLOCKED`。

## 安全结论

输出仅为离线仿真轨迹。未访问 Nano、串口、D405 或实体电机；未部署、使能、回零、置零；
未调用真实控制 API，未写共享内存，未生成电机命令、串口帧或 G-code。执行和实体授权字段
始终为 `false`。
