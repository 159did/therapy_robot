# PTR 项目正式文档

本目录是 /home/zzq/PTR/therapy_robot 的唯一正式说明入口。以后新任务只更新本目录中对应文档，不再新建 archive、progress、summary、history 或平行说明目录。

## 当前结论

- 当前主分支：main
- 整理前主分支基线：192d9c697f314b20c4b8e86ed9883f79c1ea6ff3（H1 collector encoder read optional）。
- H1/整理集成提交：bff20c7（H1 PASS、机器状态 H1_ENTITY_READONLY_PASS、正式文档、旧说明清理）；后续文档对齐提交：e8ac26d。当前精确 HEAD 以 `git rev-parse HEAD` 为准。
- 最新 B8 2/3/4 集成提交：165ef6d34ab7b084154eac8ed61682fec9d9ad21
- B8 集成内容：74a186a9627e1443258eb364748b8d0ad8a7a9d9 及其后续集成审计提交。
- Shared Memory ABI：V3，定义在 include/therapy_robot/shared_memory.hpp 的 SharedState，默认硬件模式关闭。
- H1 当前状态：`H1_BASIC_READONLY`；通过 `GET /api/h1/status` 查看设备名称和 K0-K4 通信/故障/使能状态。它不授予实体运动权限。
- Nano：已完成一次 ARM64 编译和部署快照记录；最后一次实时 SSH 核验因 `192.168.2.100:22` 超时而未完成，因此当前 Nano 运行态仍标记为 `NOT_VERIFIED`，不得把部署快照当作实时部署 PASS。
- 实体权限：`execution_allowed=false`、`entity_action_authorized=false`、`entity_motion_authorized=false`；本目录不产生或发送电机命令。
- 本次整理备份：/home/zzq/PTR/therapy_robot/docs-reorganization-backup-20260824T140646Z/；其中 `ptr-problem-archives-before-deletion/` 保存已清理的 PTR 问题归档原件、逐文件 SHA-256 和内容摘要。

## 文档导航

1. 01-开发规矩.md
2. 02-项目架构与代码位置.md
3. 03-功能与实验流程.md
4. 04-阶段进度.md
5. 05-版本与部署记录.md
6. 06-测试与证据索引.md
7. 07-历史整合记录.md
8. 08-机械臂分阶段工作流程.md（实现、坐标、接口和仿真操作统一说明）

## 保留资料

- 电机协议原文：docs/电机协议/
- 原始碰撞边界说明：docs/机箱碰撞边界.md
- 任务卡：docs/tasks/
- 测试、实验和实体只读原始证据：docs/progress/evidence/
- 历史归档索引：docs/archive/
- 原 `/home/zzq/PTR/问题归档/` 和 `/home/zzq/PTR/问题归档备份/` 已按用户要求迁移到上述整理备份并删除原目录；Nano 备份、recovery 备份、程序备份和 worktrees 未修改。

当前统一规则：H1 为 `H1_BASIC_READONLY` 轻量状态展示。实体运动授权是独立事项；`execution_allowed=false`、`entity_action_authorized=false`、`entity_motion_authorized=false` 继续保持。
