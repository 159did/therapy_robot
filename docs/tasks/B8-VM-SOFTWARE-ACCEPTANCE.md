# B8-VM-SOFTWARE-ACCEPTANCE

agent_number=3
task_name=B8-VM-SOFTWARE-ACCEPTANCE
delivery_id=agent-3/b8-vm-software-acceptance
platform=x86_64_vm
host=zzqVM
architecture=x86_64
jetson_nano=false
arm64_tested=false
nano_tested=false
entity_hardware_tested=false
entity_motion_tested=false
h1_status=H1_EVIDENCE_INCOMPLETE

基线：`9e0c4b925062b0a7c8fd2fa25fd985fe9798402b`

分支：`batch/b8-vm-software-acceptance`

worktree：`/home/zzq/PTR/worktrees/b8-vm-software-acceptance`

H1：`H1_EVIDENCE_INCOMPLETE`

## 范围与结论

本任务只对 zzqVM 上的软件构建、自动测试和隔离仿真 API 做验收。它不是 Jetson Nano、ARM64、实体硬件或实体运动验收。最终 VM 结论为：

`VM_SOFTWARE_READY_FOR_SIMULATION`

## 全新软件验收

独立构建目录为 `build/b8-vm-acceptance`，未使用旧 `bin/` 二进制作为验收结果。

```bash
cmake -S . -B build/b8-vm-acceptance -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON
cmake --build build/b8-vm-acceptance --parallel 2
ctest --test-dir build/b8-vm-acceptance --output-on-failure
python3 -m py_compile $(find scripts tests -name '*.py' -type f)
python3 -m unittest discover -s tests -p 'test_*.py'
```

结果：CMake 配置和构建成功；CTest 17/17 通过；71 个 Python 文件编译成功；Python unittest 79/79 通过。

## 隔离 API 验收

仅启动本次全新构建的 `main_core` 与 `main_web_sim`。使用：

```text
THERAPY_ROBOT_RUNTIME_DIR=/tmp/therapy_robot_b8_vm_acceptance
THERAPY_ROBOT_SHM_NAME=/therapy_robot_b8_vm_acceptance_shm
THERAPY_ROBOT_SIM_WEB_PORT=47043
```

九个指定 GET 均返回 HTTP 200。五个历史 404 接口 `/api/workflow/state`、`/api/workflow/self_check`、`/api/acupoints/latest` 及左右 `/api/motion_test/points` 均不再返回 404。

GET 前后及仿真请求后，下列状态完全不变：

- `command_seq=0`
- `target_command_seq=0`
- `endpoint_target_seq=0`
- 所有 group `hardware_enabled=0`
- 所有 motor `enabled=0`
- 所有 motor 目标字段为 0

只向 `/api/motion_test/simulate` 发送左右仿真 JSON；未发送其他 POST。左右均满足 `simulation_only=true`、`motor_command_written=false`，重复结果稳定。两侧都被现有机箱净空规则确定性拒绝：净空 `13.085 mm` 小于要求的 `30 mm`。这是 VM 仿真安全拒绝，不是实体运动结果。只读认证还确认 `execution_allowed=false`、`entity_action_authorized=false`。

## 清理与安全边界

本任务启动的两个进程均已停止，47043 不再监听，专用共享内存已释放。未删除项目文件、其他人的运行目录或默认共享内存。

未连接真实 Nano，未访问实体串口或 D405，未启动硬件模式，未使能、回零、置零或移动实体电机，未生成实体电机命令。VM 通过不得解释为 Nano、ARM64、硬件或 H1 通过。

证据目录：`docs/progress/evidence/B8-VM-SOFTWARE-ACCEPTANCE/`。
