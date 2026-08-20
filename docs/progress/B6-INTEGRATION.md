# B6 集成进度

集成前基线：`659a1e51f0ef27c934ddbd1add177383eedfe92b`

## 集成顺序

1. `B6-SAFETY-BASELINE`
2. `B6-EE-CONTRACT`
3. `B6-EE-SIM`

## 审核结论

- 三个分支均从同一基线开始，提交范围独立，未发现硬件访问或电机控制入口。
- 单项测试在合并前分别为 16、19、17 项通过。
- 发现并修复一项接口冲突：末端契约要求
  `nano_deployment_authorized=false`，原仿真器没有接收该字段。
- 仿真器现复用 `scripts/b6/validate_end_effector_command.py` 作为唯一命令校验来源，
  避免契约规则出现两份实现。
- 新增离线流水线，固定按“安全判断、契约校验、仿真”执行；任一阶段失败即停止。

## 权限边界

本阶段只允许离线仿真。以下输出在契约、流水线和仿真报告中均固定为 `false`：

- `execution_allowed`
- `entity_action_authorized`
- `nano_deployment_authorized`
- `motor_command_generated`
- `motor_target_generated`
- `serial_payload_generated`

## 软件验证

- B6 定向测试：57 项通过（安全 16、契约 19、联合 5、仿真 17）。
- B4 回归：31 项通过。
- B5 路线/视觉/演示定向回归：19 项通过。
- 仓库顶层测试：72 项通过。
- 按不重复用例计，共验证 143 项。
- Python 编译检查和 `git diff --check` 通过。
- 验证过程未连接 Nano、实体串口或 D405，未启动硬件服务，未生成电机命令。

## 下一步

- 周六只在专用 H1 分支执行只读检查并保存记录。
- 专用分支：`execution/b6-h1-saturday-readonly`。
- H1 未通过前，不新增实体末端控制入口。
- H1 通过后，先做低速、短距离、非接触末端验证，再考虑实体适配层。
