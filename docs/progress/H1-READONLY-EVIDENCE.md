# H1-READONLY-EVIDENCE 进度

分支：`batch/h1-readonly-evidence`

## 当前正式结论（已降级为轻量只读）

```text
H1_CURRENT_STATUS=H1_BASIC_READONLY
entity_motion_authorized=false
hardware_control_authorized=false
```

## 当前有效信息

- H1 只展示设备名称、运行模式和 K0-K4 的 online、fault、enabled、当前位置。
- 通过 `GET /api/h1/status` 获取，不要求完整实体证据包。

## 范围规则

H1 是信息展示，不是实体运动授权。完整实体身份、操作者、串口占用、急停、看门狗、
软限位、SHA-256 和连续采样属于可选审计，不再作为 H1 启动条件或控制门槛。

历史准备材料和旧窗口仍可用于追溯，但不代表当前结论；当前状态以本页和
`GET /api/h1/status` 的实时返回为准。
