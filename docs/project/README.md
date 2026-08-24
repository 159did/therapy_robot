# PTR 项目正式文档

本目录是 /home/zzq/PTR/therapy_robot 的唯一正式说明入口。以后新任务只更新本目录中对应文档，不再新建 archive、progress、summary、history 或平行说明目录。

## 当前结论

- 当前主分支：main
- 当前最新主分支提交：192d9c697f314b20c4b8e86ed9883f79c1ea6ff3（H1 collector encoder read optional）
- 当前工作树存在用户未提交修改：docs/H1-READONLY-COLLECTOR.md、tests/test_h1_readonly_collector.py；整理过程保留，不覆盖、不回滚。
- 最新 B8 2/3/4 集成提交：165ef6d34ab7b084154eac8ed61682fec9d9ad21
- B8 集成内容：74a186a9627e1443258eb364748b8d0ad8a7a9d9 及其后续集成审计提交。
- Shared Memory ABI：V3，定义在 include/therapy_robot/shared_memory.hpp 的 SharedState，默认硬件模式关闭。
- H1：不是 PASS。当前为 H1_ENTITY_READONLY_PASS，实体运动必须保持锁定。
- Nano：当前已部署主工程版本由 Nano 本机 ARM64 构建和 software-provenance-192d9c6.json 记录；zzqVM 仅是软件开发主机。
- 本次整理备份：/home/zzq/PTR/therapy_robot/docs-reorganization-backup-20260824T140646Z/

## 文档导航

1. 01-开发规矩.md
2. 02-项目架构与代码位置.md
3. 03-功能与实验流程.md
4. 04-阶段进度.md
5. 05-版本与部署记录.md
6. 06-测试与证据索引.md
7. 07-历史整合记录.md

## 保留资料

- 电机协议原文：docs/电机协议/
- 原始碰撞边界说明：docs/机箱碰撞边界.md
- 任务卡：docs/tasks/
- 测试、实验和实体只读原始证据：docs/progress/evidence/
- 历史归档索引：docs/archive/
- PTR 外部问题归档、Nano 备份和程序备份不在本目录中，且本次未修改。
\n\n当前统一规则：H1_ENTITY_READONLY_PASS 只表示实体反馈读取和未动作审计通过；execution_allowed=false、entity_action_authorized=false、entity_motion_authorized=false 继续保持，任何实体运动仍需单独授权。\n