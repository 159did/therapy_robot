# B6-SAFETY-BASELINE 进度记录

任务：建立末端控制前的软件安全基础
基线工程：`/home/zzq/PTR/therapy_robot`
基线提交：`659a1e51f0ef27c934ddbd1add177383eedfe92b`
分支：`batch/b6-safety-baseline`
工作树：`/home/zzq/PTR/worktrees/b6-safety-baseline`
状态：完成，待集成
范围：纯软件、离线验证；未访问 Nano、串口、D405 或电机

## 修改文件

- `scripts/b6/safety_baseline.py`：新增集中式安全状态、模式和 fail-closed 判定。
- `tests/b6/test_safety_baseline.py`：新增纯软件单元测试。
- `docs/progress/B6-SAFETY-BASELINE.md`：本任务记录。
- `docs/progress/evidence/B6-SAFETY-BASELINE/unit-test.log`：B6 单元测试输出。
- `docs/progress/evidence/B6-SAFETY-BASELINE/regression-tests.log`：B4/B5、H1 只读和离线 Demo 回归输出。
- `docs/progress/evidence/B6-SAFETY-BASELINE/hardware-processes.log`：机器人相关进程只读检查输出；空文件表示无匹配进程。
- `docs/progress/evidence/B6-SAFETY-BASELINE/therapy-shm.log`：therapy 共享内存只读检查输出；空文件表示不存在。
- `docs/progress/evidence/B6-SAFETY-BASELINE/control-ports.log`：8080/8081 监听只读检查输出；空文件表示无监听。
- `docs/progress/evidence/B6-SAFETY-BASELINE/source-audit.md`：现有控制入口、状态字段、权限字段及 B4/B5 安全逻辑审核。
- `docs/progress/evidence/B6-SAFETY-BASELINE/device-access-check.md`：实体设备零访问证据说明。

未修改 B6-EE-CONTRACT、B6-EE-SIM、实体启动脚本、B4/B5 既有仿真和只读接口。

## 现有实现审核

审核详情见 `source-audit.md`。结论如下：

- 现有 HTTP 控制入口集中在 `src/web/main_web.cpp`，实体执行和看门狗/急停处理集中在 `src/motor/main_motor.cpp`；本任务未接线、未调用、未修改这些实体路径。
- `include/therapy_robot/shared_memory.hpp` 和 `src/common/shared_memory_defaults.cpp` 已有仿真/硬件状态，其中 `hardware_mode` 默认值为 0；B6 使用独立、可读的三值枚举，避免布尔含义歧义。
- `src/common/readiness.cpp`、`src/common/workflow.cpp` 已有急停、碰撞等只读检查，并保持 `execution_allowed=false`、`entity_action_authorized=false`。
- B4 授权契约和安全包固定权限字段为 false；B4 M1/M2 仿真严格检查合成标记、单位、有限数值和未知字段，并对急停、看门狗、反馈丢失安全停止。
- B5 路线适配器和离线 Demo 延续 `synthetic=true`、权限锁定和 fail-closed 规则；本任务的新增模块不改变其输入输出。
- B6 当前是未来控制入口必须调用的纯判定门，不包含串口或电机写入。后续集成必须显式接入，不能把“模块存在”误认为现有实体入口已经受它保护。

## 运行模式

| 模式 | 默认 | 允许行为 |
|---|---:|---|
| `SIMULATION` | 是 | 仅允许 `offline_simulation`，不产生实体命令 |
| `HARDWARE_READONLY` | 否 | 只读状态/观测，拒绝实体控制 |
| `HARDWARE_CONTROL` | 否 | 只有全部安全门通过时才可被未来控制入口接受 |

默认 `SafetyState.default()` 为 `SIMULATION`，且 `execution_allowed=false`、`entity_action_authorized=false`。

## 集中式安全状态字段

| 字段 | 定义 |
|---|---|
| `execution_allowed` | 当前是否允许执行；默认 false |
| `entity_action_authorized` | 是否明确获得实体动作权限；默认 false |
| `hardware_mode` | `SIMULATION`、`HARDWARE_READONLY` 或 `HARDWARE_CONTROL` |
| `emergency_stop` | 急停是否有效/锁存 |
| `feedback_valid` | 反馈是否有效 |
| `feedback_age_ms` | 反馈年龄；超过 250 ms 视为过期 |
| `limit_state` | `CLEAR` 或 `ABNORMAL` |
| `collision_state` | `CLEAR` 或 `ABNORMAL` |
| `watchdog_state` | `OK` 或 `TIMEOUT` |
| `h1_status` | 必须为 `PASS` 才能进入实体控制判定 |

## 统一拒绝规则

实体控制请求必须同时满足：明确 `HARDWARE_CONTROL`、H1=`PASS`、无急停、反馈有效且未过期、看门狗=`OK`、软限位=`CLEAR`、碰撞=`CLEAR`、`execution_allowed=true`、`entity_action_authorized=true`，并且输入字段严格匹配、单位为 `normalized`、数值有限。任意条件不满足即拒绝，并返回稳定的拒绝原因；不会执行动作。

离线仿真是显式例外：仅在 `SIMULATION` 中接受 `offline_simulation`，且结果仍保持 `execution_allowed=false`。

## 拒绝原因

已覆盖：

```text
hardware_control_mode_not_explicit
h1_status_not_pass
emergency_stop_active
feedback_invalid
feedback_expired
watchdog_timeout
limit_state_abnormal
collision_state_abnormal
entity_action_not_authorized
execution_not_allowed
input_non_finite
units_not_supported
unknown_input_field:<field>
```

## 测试命令和结果

```bash
python3 -m py_compile scripts/b6/safety_baseline.py tests/b6/test_safety_baseline.py
python3 -m unittest -v tests/b6/test_safety_baseline.py

python3 -m unittest -v \
  tests/b4_prep/test_m1_m2_motion_sim.py \
  tests/b5/test_m1_m2_route_sim.py \
  tests/test_b5_h1_preflight.py \
  tests/test_b5_offline_demo.py \
  tests/test_b5_demo_adapter.py \
  tests/test_b5_demo_flow.py
```

结果：B6 16 项测试通过；B4/B5、H1 只读和离线 Demo 32 项回归通过。覆盖正常 SIMULATION 离线仿真允许、HARDWARE_READONLY 拒绝、两个权限字段分别拒绝、仅解锁权限仍拒绝、所有实体控制安全门拒绝、严格输入校验、故障安全停止、只读预检和既有 Demo。测试只导入或执行离线 Python 模块，不启动机器人进程、不打开设备、不写入控制接口。

## 未访问实体设备证据

- 代码仅依赖 Python 标准库 `math`、`dataclasses` 和类型定义。
- 未导入串口、D405、socket、subprocess、共享内存或部署模块。
- 本任务没有执行 Nano、串口、D405、电机、使能、回零、置零或实体启动脚本。
- 本任务输出只是 `SafetyDecision`，没有运动目标、实体 offset、K0 高度或电机命令生成路径。
- 只读检查结果：机器人相关进程 0，therapy 共享内存不存在，8080/8081 无监听；见 `device-access-check.md` 和对应空日志。

## 后续集成注意事项

1. 未来控制入口必须先构造完整 `SafetyState`，再调用 `evaluate_control_request` 或 `authorize_control`。
2. 控制入口只能把 `allowed=true` 作为“安全门通过”的软件判定，不得绕过该模块直接写串口或调用电机 API。
3. `HARDWARE_READONLY` 不能升级为控制；进入 `HARDWARE_CONTROL` 必须由更高层授权流程显式产生，并保留审计证据。
4. 当前“全部门通过”测试只证明判定逻辑，不代表实体 H1、实体电机或整机安全通过。
5. 本分支没有把 B6 判定门接入 `src/web/main_web.cpp` 或 `src/motor/main_motor.cpp`；未来实体集成必须在所有运动入口统一调用并增加不可绕过测试。
