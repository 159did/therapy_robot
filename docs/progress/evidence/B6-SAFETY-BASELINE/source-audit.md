# B6-SAFETY-BASELINE 源码审核记录

基线：`659a1e51f0ef27c934ddbd1add177383eedfe92b`

## 控制入口

- `src/web/main_web.cpp` 暴露现有 HTTP 命令入口并读取共享状态。
- `src/motor/main_motor.cpp` 包含实体电机执行、急停、碰撞和看门狗处理。
- `scripts/run-jetson-hardware.sh` 是实体启动脚本。

本任务未修改、未调用上述实体路径。新增 `scripts/b6/safety_baseline.py` 只对安全状态和控制意图做纯判定，不产生运动目标或设备写入。

## 状态与权限字段

- `include/therapy_robot/shared_memory.hpp` 已有 `hardware_mode`、`emergency_stop` 等运行状态；`src/common/shared_memory_defaults.cpp` 将 `hardware_mode` 默认置为 0。
- `src/common/readiness.cpp` 和 `src/common/workflow.cpp` 已有急停、碰撞和准备状态检查，离线输出固定保持 `execution_allowed=false` 和 `entity_action_authorized=false`。
- B4/B5 文档和离线结果广泛使用 `execution_allowed`、`entity_action_authorized`、`nano_deployment_authorized`、`formal_use_allowed` 和 `promotion_locked`。

B6 将进入未来控制判定所需的最小状态集中为十个字段，并对缺失字段、未知字段、错误类型和未知枚举值失败关闭。

## B4/B5 安全逻辑

- `scripts/b4_prep/authorization_contract.py` 和 `build_safety_package.py` 将实体权限固定为 false，阻止离线材料晋升为实体授权。
- `scripts/b4_prep/m1_m2_motion_sim.py` 对合成来源、单位、有限数值、未知字段、最小速度/位移和停止距离做严格检查；急停、看门狗超时和反馈丢失进入安全停止。
- `scripts/b5/m1_m2_route_sim.py` 复用 B4 仿真，保持 `synthetic=true`、`execution_allowed=false`、`entity_action_authorized=false`。
- `scripts/b5_demo_adapter.py`、`b5_demo_flow.py` 和 `b5_offline_demo.py` 对权限解锁、哈希变化、缺失输入和路线失败保持 fail-closed。
- `scripts/b5_h1_preflight.py` 是只读预检，不把检查结果转换为实体执行权限。

## B6 设计结论

- 默认模式使用 `SIMULATION`，两个权限字段默认 false。
- `HARDWARE_READONLY` 和未明确选择的模式都不能执行实体控制。
- 只有显式 `HARDWARE_CONTROL` 且所有安全门同时通过，纯判定结果才可能为 allowed。
- `offline_simulation` 只在 `SIMULATION` 中允许，返回结果仍为 `execution_allowed=false`。
- 当前模块是未来控制入口的统一判定契约，尚未接入现有实体入口；接入属于后续任务，必须单独验证不可绕过性。
