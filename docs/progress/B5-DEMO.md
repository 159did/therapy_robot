# B5-DEMO 进度

任务基线：`d8ad99a8270121eecad61f576710ee31d2b34a25`  
分支：`batch/b5-demo`  
worktree：`/home/zzq/PTR/worktrees/b5-demo`

当前状态：待集成（纯软件离线演示）

| 步骤 | 状态 | 证据 |
|---|---|---|
| DEMO-01 建立分支/worktree和安全边界 | 已完成 | `docs/B5-DEMO.md` |
| DEMO-02 独立 fixture 离线流程 | 已完成 | `scripts/b5_demo_flow.py` |
| DEMO-03 独立流程正常/失败测试 | 已完成 | `tests/test_b5_demo_flow.py` |
| DEMO-04 独立流程左右输出 | 已完成 | `nominal-left.json`、`nominal-right.json` |
| DEMO-05 首版交付验证 | 已完成 | 提交 `f8957a4` |
| DEMO-06 2号路线/3号视觉输入适配层 | 已完成 | `scripts/b5_demo_adapter.py` |
| DEMO-07 左右闭环和阻断证据 | 已完成 | `adapter-left.json`、`adapter-right.json`、`adapter-route-blocked.json`、`adapter-hash-blocked.json` |
| DEMO-08 适配器失败路径与安全回归 | 已完成 | `tests/test_b5_demo_adapter.py`、`verification.txt` |

## 输入来源

2号 `batch/b5-m1-m2@c7ba475` 生成的左右 `PASS` 路线输出 SHA-256 为
`a99feb5d...9323` 和 `1b0762f6...f187`。3号 `batch/b5-vision@1b52302` 的已跟踪
`B5-VISION-OUTPUT.example.json` SHA-256 为 `be04071f...91c64`，pipeline id 为
`vision-9e2633f99c52a19fc0401a0e`。本任务只读取并保存输出 JSON，未合并或修改 2 号、
3 号分支，也未修改 main。

左右正常路径均为：

`IDLE -> SAFE_HIGH -> CAMERA_READY -> ACUPOINT_FOUND -> APPROACH_SIMULATED -> HOLD -> RETRACT -> RETURN_HIGH -> COMPLETE`

选中穴点为大椎，候选末端位置为
`[0.1609163181992805, 0.1728330895391088, 1.2935009362530452]`。
路线 `watchdog_timeout` 的 `FAIL_CLOSED` 被适配器转为 `BLOCKED`；错误输入哈希也为
`BLOCKED`。测试覆盖视觉失败、置信度不足、格式错误、安全字段缺失，以及路线/视觉中
任一权限字段变为 `true`。

## 安全边界

未访问 Nano、实体串口或 D405；未部署 Nano；未使能、回零或移动电机；未生成 motor
command；未调用控制 POST；未修改自动锁或增加控制接口。所有结果仅为仿真，执行和
实体授权字段固定为 `false`。
