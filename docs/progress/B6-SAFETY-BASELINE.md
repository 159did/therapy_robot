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

未修改 B6-EE-CONTRACT、B6-EE-SIM、实体启动脚本、B4/B5 既有仿真和只读接口。

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
```

结果：15 项测试通过（包含正常 SIMULATION 离线仿真允许、HARDWARE_READONLY 拒绝、两个权限字段分别拒绝、所有实体控制安全门拒绝、依赖扫描和一个全部门通过的纯判定测试）。测试只导入 Python 模块，不启动进程、不打开设备、不写入控制接口。

## 未访问实体设备证据

- 代码仅依赖 Python 标准库 `math`、`dataclasses` 和类型定义。
- 未导入串口、D405、socket、subprocess、共享内存或部署模块。
- 本任务没有执行 Nano、串口、D405、电机、使能、回零、置零或实体启动脚本。
- 本任务输出只是 `SafetyDecision`，没有运动目标、实体 offset、K0 高度或电机命令生成路径。

## 后续集成注意事项

1. 未来控制入口必须先构造完整 `SafetyState`，再调用 `evaluate_control_request` 或 `authorize_control`。
2. 控制入口只能把 `allowed=true` 作为“安全门通过”的软件判定，不得绕过该模块直接写串口或调用电机 API。
3. `HARDWARE_READONLY` 不能升级为控制；进入 `HARDWARE_CONTROL` 必须由更高层授权流程显式产生，并保留审计证据。
4. 当前“全部门通过”测试只证明判定逻辑，不代表实体 H1、实体电机或整机安全通过。
