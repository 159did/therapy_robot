# B4-PREP-A-01 实体窗口授权与回滚契约

状态：冻结（纯软件准备，未授予实体权限）  
契约版本：`b4.prep.a.v1`  
基线：`a2d7b7cef590258d2a62bf03814e5d67b9b59c97`

## 目的与边界

该契约是实体窗口前的计划材料和审计输入，不是 capability token，不会被控制路径消费。它不启动进程、不连接串口、不访问 D405、不写共享内存，也不允许 Nano 部署或任何电机动作。

状态只有三种：`PREPARED`（软件材料已整理）、`REQUESTED`（提交独立安全负责人等待批准）、`AUTHORIZED`（独立实体窗口已批准）。B4-PREP-A 只能产生 `PREPARED`。

## 顶层字段与失败关闭

字段包括 `window_id`、`scope`、`issued_at_ms`、`expires_at_ms`、`revoked`、`revocation_reason`、`operator_confirmation`、`rollback_owner`、`evidence_manifest`、`entity_access_declaration`、`execution_allowed`、`entity_action_authorized`、`nano_deployment_authorized`，另有 `schema_version`、`status` 和稳定的 `contract_id`。

所有实体访问、执行和 Nano 授权字段必须为 `false`；有效期最长 300 秒；scope 必须非空且规范排序；证据清单是文件名和 SHA-256；ID 对除自身外的规范 JSON 做 SHA-256。缺字段、未知字段/schema、scope 不匹配、超时、时间倒退、撤销、权限或实体访问字段为 true、证据哈希或 ID 不一致，均返回 `valid=false`，不做任何副作用。

验证通过只说明“软件准备材料自洽”，不等于 H1、M1、M2、V2-F、T1 或 S1 获得批准。实体窗口必须由用户/独立安全负责人另行明确设备、操作者、目标、停止条件和回滚人。
