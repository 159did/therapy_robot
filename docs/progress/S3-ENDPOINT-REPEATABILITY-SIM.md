# S3 末端重复定位自动循环进度

状态：`SOFTWARE_SIMULATION_PASS`

- 分支：`work/s3-endpoint-positioning`
- 平台：`platform=x86_64_vm`、`host=zzqVM`
- 输入：用户手动选择点位 CSV；支持 UTF-8 BOM、LF/CRLF 和字段首尾普通空白，同时保持字段数、schema、有限数值、非空/唯一 point_id 严格校验。
- 次数：默认每点 3 次，可通过 `--repetitions N` 选择 1 至 100 次；非法值返回 2。
- 循环：到点、稳定、读取模拟 K0-K4、FK、验收、在目标周围 `BASE_XY` 圆周随机退开 15 mm、从退开点再次返回目标。
- 随机退开：默认 seed=`20260827`，最多尝试 36 个方向；Z 和姿态不变，退开与返回路径均通过现有 IK、正式软限位和 required collision config 预检。
- 状态机：正常完成为 `COMPLETE`；移动超时、稳定超时、反馈丢失和预检失败均为 `STOPPED`。
- 报告：逐次 CSV 和包含事件/每点统计的 JSON。
- 确定性：相同输入、seed 和 repetitions 产生字节级相同的 JSON/CSV，不同 seed 改变退开角度。
- 示例：2 个合成点，共 6 次，每次测后均局部退开，全部 accepted，整个实验最终返回模拟安全起点。
- 审核修复验证：新构建目录 `build/s3-review-fix`；完整 CTest、显式 5 次循环结果以本次提交记录为准。
- 说明：这是 zzqVM `x86_64_vm` 合成反馈的软件流程验证，不是实体机械臂运动、Nano/ARM64 验证或实体重复定位精度。

安全边界：`nano_tested=false`、`arm64_tested=false`、`entity_hardware_tested=false`、`serial_accessed=false`、`d405_accessed=false`、`shared_memory_written=false`、`motor_target_generated=false`、`motor_command_generated=false`、`execution_allowed=false`、`entity_action_authorized=false`、`entity_motion_authorized=false`。

## 实体测试适配预检

- 新增 `scripts/s3_endpoint_repeatability_preflight.py`：只读取人工采集的 JSON 状态快照，检查 Nano/aarch64 身份、S3 提交、H1、`HARDWARE_CONTROL`、反馈年龄、看门狗、软限位、碰撞、抱闸、急停、工作区、操作者、急停负责人、request/authorization ID 和 1..100 次重复参数。
- 预检通过时只输出 `READY_FOR_MANUAL_REVIEW`，`go=false`、`motion_authorized=false`；任一条件失败输出 `NO_GO`。该工具不连接设备、不启动进程、不打开串口、不写共享内存、不生成电机目标或命令。
- 快照模板：`tests/fixtures/s3-entity-preflight-snapshot.example.json`。模板默认使用占位/失败值，不可直接作为实体 PASS。
- 新增 CTest：`s3_endpoint_repeatability_preflight`。今晚的正确顺序是：Nano 只读采集 -> 填写快照 -> 运行预检 -> 人工复核，不能跳过预检直接执行实体运动。

回滚：撤销本任务提交即可；本任务未修改正式实体配置、offset、软限位或碰撞边界。

## 审核修复：CSV 兼容与可配置重复次数

- 构建目录：`build/s3-review-fix`；基线分支为 `work/s3-endpoint-positioning`，未合并 main。
- CSV：支持 UTF-8 BOM、LF、Windows CRLF，以及表头和字段首尾普通空白；字段数量、字段名、有限数值、非空且唯一 `point_id` 校验保持严格，错误输入仍返回码 2。
- 重复次数：`--repetitions N`，默认 `3`，只接受十进制正整数 `1..100`；JSON、CSV、arrival_type 和每点汇总均使用实际 N。每轮测量后仍先随机退开 15 mm `BASE_XY` 圆周点，最后一轮退开完成后才返回模拟安全起点。
- 专项测试：`python3 tests/test_endpoint_repeatability_sim.py --tool build/s3-review-fix/endpoint_repeatability_sim --points tests/fixtures/endpoint_positioning/repeatability_points.csv --collision-config config/enclosure-collision.csv --source tools/endpoint_repeatability_sim.cpp`，结果 `PASS`。
- 完整回归：`ctest --test-dir build/s3-review-fix --output-on-failure -j2`，结果 `27/27 tests passed, 0 tests failed`。
- 显式 5 次命令：`build/s3-review-fix/endpoint_repeatability_sim --points tests/fixtures/endpoint_positioning/repeatability_points.csv --collision-config config/enclosure-collision.csv --repetitions 5 --random-seed 20260827 --json /tmp/s3-repeatability-5-report.json --csv /tmp/s3-repeatability-5-table.csv`；结果 `status=PASS`、`selected_points=2`、`repetitions_per_point=5`、`planned_samples=10`、`completed_samples=10`、`safe_start_returned=true`，CSV 10 行（左右各 5 行）。
- 5 次 arrival_type：每个点第 1 行为 `INITIAL_APPROACH`，后 4 行为 `RETURN_AFTER_RETREAT`。
- 5 次报告安全字段：`execution_allowed=false`、`entity_action_authorized=false`、`entity_motion_authorized=false`、`motor_command_generated=false`、`motor_target_generated=false`、`serial_payload_generated=false`、`shared_memory_written=false`、`serial_accessed=false`、`d405_accessed=false`、`nano_tested=false`、`arm64_tested=false`、`entity_hardware_tested=false`。
- 本次仍是 `platform=x86_64_vm`、`host=zzqVM` 纯软件仿真，不是实体机械臂运动、Nano 验证或实体重复定位精度证据。
