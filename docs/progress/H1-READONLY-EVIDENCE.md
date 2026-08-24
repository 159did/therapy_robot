# H1-READONLY-EVIDENCE 进度

分支：`batch/h1-readonly-evidence`

## 当前正式结论

```text
H1_CURRENT_STATUS=H1_ENTITY_READONLY_PASS
entity_motion_authorized=false
hardware_control_authorized=false
```

## 当前有效证据

- 真实 Nano：`jetsonorin@192.168.2.100`，hostname `ubuntu`，架构 `aarch64`。
- 当前窗口：`docs/progress/evidence/H1-READONLY-EVIDENCE/entity-raw/20260824T125208Z/`。
- K0-K4 共 50 条样本，每轴 10 条。
- 五轴在线、无故障、未使能、速度为 0。
- 未发送 enable、disable、stop、home、zero、jog、move、target、setpoint 或 brake-release。
- 未生成电机命令或目标，未发生运动，未访问 D405。
- K0 逻辑位置 `43206 native`，逻辑高度 `3.00041666667 mm`。
- 原始 SHA-256 manifest 已验证。

## 范围规则

本 PASS 只表示实体反馈读取和未动作审计通过，不表示运动控制授权或人体接触授权。急停软件读回、硬件看门狗、控制面板、K1-K4 抱闸、homed、zeroed、限位和碰撞状态不属于本次只读 PASS 条件；K1-K4 抱闸为 `not_applicable`。

历史准备材料和旧窗口仍可用于追溯，但不代表当前结论；所有当前阅读应以本页和 `20260824T125208Z/report.json` 为准。
