# B7-API-CONTRACT-CHECK

## 目标

确认部署预检中出现 404 的 readiness、workflow 和 motion-plan 只读 API 是否存在于当前源码，
并在新构建的隔离环境中验证接口契约。该任务不访问实体串口、D405 或电机控制入口。

## 结论

当前源码已注册以下接口：

```text
GET /api/readiness/attestation
GET /api/workflow/state
GET /api/workflow/self_check
GET /api/motion_plan/preview?side=left
GET /api/motion_plan/preview?side=right
```

在全新 `build/b7-api` 构建上，三个黑盒 API 测试全部通过：

```text
workflow_api:    Passed
motion_plan_api: Passed
readiness_api:   Passed
3/3 tests passed
```

因此之前 Nano 默认仿真服务返回的 404 不是当前源码缺少路由，而是启动了旧的仿真二进制。
修复方式是重新编译并用新构建启动隔离仿真；本任务不直接替换 Nano 默认程序。

## 安全边界

- API 测试使用临时端口、临时运行目录和临时共享内存名称。
- GET 接口验证不改变 command、target、motor 或 runtime 状态。
- motion-plan 只生成 synthetic preview，`execution_allowed=false`，不生成实体命令。
- 未启动 `scripts/run-jetson-hardware.sh`，未访问串口/D405，未使能、回零、置零或移动电机。

## 后续集成

1. 由集成代理审核本任务证据。
2. 使用本分支的新构建启动仿真，再复核指定 GET API。
3. 不要把旧服务的 404 误判为源码 API 缺失。
4. API 复核通过后，更新 Nano 预检报告；实体状态仍需 H1 只读结论。
