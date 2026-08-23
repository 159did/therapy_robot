# B7-API-CONTRACT-CHECK 进度

任务：确认 readiness/workflow/motion-plan 只读 API 契约
分支：`batch/b7-api-contract-check`
工作区：`/home/zzq/PTR/worktrees/b7-api-contract-check`
状态：完成，待集成

| 步骤 | 内容 | 状态 | 证据 |
|---|---|---|---|
| B7-API-01 | 从当前 main 创建独立 worktree | 完成 | Git 状态 |
| B7-API-02 | 审核 C++ 路由注册和现有黑盒测试 | 完成 | `route-source-audit.txt` |
| B7-API-03 | 全新隔离构建 | 完成 | `cmake-configure.log`、`cmake-build.log` |
| B7-API-04 | 运行三个只读 API CTest | 完成 | `api-ctest.log` |
| B7-API-05 | 更新结论和交付 | 完成 | 本文件、任务卡、commit |

## 结果

```text
workflow_api: 1/1 Passed
motion_plan_api: 1/1 Passed
readiness_api: 1/1 Passed
总计：3/3 Passed
```

之前 Nano 默认服务的 404 归因：旧仿真二进制未包含当前源码中的路由注册；不是当前源码缺少接口。

## 硬件边界

只进行了源码审核和隔离软件构建/测试；没有启动 Nano 仿真服务，没有访问串口、D405 或实体电机。
