# B5-DEMO 进度

任务基线：`d8ad99a8270121eecad61f576710ee31d2b34a25`
分支：`batch/b5-demo`
worktree：`/home/zzq/PTR/worktrees/b5-demo`

当前状态：待集成（纯软件离线演示）

| 步骤 | 状态 | 证据 |
|---|---|---|
| DEMO-01 建立分支/worktree和安全边界 | 已完成 | 本提交及 `B5-DEMO.md` |
| DEMO-02 离线流程编排器 | 已完成 | `scripts/b5_demo_flow.py` |
| DEMO-03 正常路径和失败路径测试 | 已完成 | `tests/test_b5_demo_flow.py` |
| DEMO-04 左右侧 JSON 输出和演示说明 | 已完成 | `docs/progress/evidence/B5/DEMO/` |
| DEMO-05 交付验证 | 已完成 | 本文件末尾及交付证据 |

## 流程结果

正常路径：`IDLE -> SAFE_HIGH -> CAMERA_READY -> ACUPOINT_FOUND -> APPROACH_SIMULATED -> HOLD -> RETRACT -> RETURN_HIGH -> COMPLETE`。

失败路径：图片缺失、视觉识别/置信度失败、路线仿真失败、输入哈希变化或任一权限字段为 `true` 时进入 `BLOCKED`；演示停止请求进入 `STOPPED`。

## 安全边界

未访问实体串口/D405，未部署 Nano，未使能/回零/移动电机，未发送实体运动指令，未增加绕过现有锁定的控制接口。输出中的执行和实体访问字段全部为 `false`。

## 验证命令

```text
python3 -m unittest -v tests/test_b5_demo_flow.py
python3 -m py_compile scripts/b5_demo_flow.py tests/test_b5_demo_flow.py
git diff --check
```
