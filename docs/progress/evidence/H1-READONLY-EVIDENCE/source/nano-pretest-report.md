# Nano 部署前软件预检报告

结论：SOFTWARE_BLOCKED

检查日期：2026-08-23（Asia/Shanghai）
目标：zzq@192.168.216.129:22
项目：/home/zzq/PTR/therapy_robot
主机名：zzqVM

## 软件提交与同步

- Nano 当前分支：main
- Nano 当前 HEAD：88e7cae85977eab33d427f20dc828c856b1a80b8
- Nano 工作树：同步前后均干净，无未说明修改。
- 本地已确认的 B6 提交：f291130d08ca41a66d396f13162316363ac16ba9
- B6 提交已在 Nano 当前 main 历史中，未执行 reset、pull、push、标签操作或强制覆盖。
- B6 文件在 Nano 与本地 SHA-256 完全一致，因此没有重复覆盖：

| 类别 | 文件 |
|---|---|
| C++ 源码 | 无 |
| Python/Shell 脚本 | scripts/b6/safety_baseline.py |
| Web 前端 | 无 |
| 测试文件 | tests/b6/test_safety_baseline.py |
| 文档 | docs/progress/B6-SAFETY-BASELINE.md；docs/progress/evidence/B6-SAFETY-BASELINE/source-audit.md；docs/progress/evidence/B6-SAFETY-BASELINE/device-access-check.md |
| 配置和标定文件 | 无 |

未复制 .git/、私钥、Token、密码、.env、未确认二进制、临时日志、个人图像、正式标定/offset/软限位/碰撞配置。

## 备份

Nano 当前版本已备份到：

/home/zzq/PTR/backups/pre-test-20260822-102502

备份包含 HEAD、Git 状态、差异摘要、CMakeLists、scripts/、src/、include/、web/、tests/ 和 config/。没有删除或覆盖旧备份。

## 编译与离线测试

编译命令：

    cmake -S . -B build/nano-pretest -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON
    cmake --build build/nano-pretest --parallel 2

结果：通过。main_core、main_control、main_motor、main_sim、main_web_control、main_web_sim 及 C++ 测试目标均生成。仅有已有未使用函数/变量警告。

CTest 命令：

    ctest --test-dir build/nano-pretest --output-on-failure

结果：17/17 通过，0 项失败，完整耗时 66.21 秒。

随后按隔离测试要求停止了当前仿真服务，仅停止其运行目录
`/tmp/therapy_robot_codex_demo/processes.pid` 中登记的仿真进程，并释放了精确的
共享内存对象 `/dev/shm/therapy_robot_shared_state`。未删除项目文件、日志或备份。
在干净状态下重跑：

    ctest --test-dir build/nano-pretest --output-on-failure -R 'shared_memory_isolation|runtime_isolation'

结果：2/2 通过（100%）。隔离重测日志位于：

    docs/progress/evidence/nano-pretest/run-20260823-175851/isolation-retest.log

Python 命令：

    python3 -m py_compile $(find scripts tests -name '*.py' -type f)
    python3 -m unittest discover -s tests -p 'test_*.py'

结果：py_compile 通过；Python unittest 为 Ran 76 tests，OK。

日志位置：

- docs/progress/evidence/nano-pretest/run-20260822-104003/cmake-configure.log
- docs/progress/evidence/nano-pretest/run-20260822-104003/cmake-build.log
- docs/progress/evidence/nano-pretest/run-20260822-104003/ctest.log
- docs/progress/evidence/nano-pretest/run-20260822-104003/python-pycompile.log
- docs/progress/evidence/nano-pretest/run-20260822-104003/python-unittest.log

## 仿真服务与网页

目标端此前存在仿真服务，使用：

- THERAPY_ROBOT_RUNTIME_DIR=/tmp/therapy_robot_codex_demo
- THERAPY_ROBOT_SHM_NAME=/therapy_robot_shared_state
- THERAPY_ROBOT_WEB_PORT=8080
- THERAPY_ROBOT_SIM_WEB_PORT=8081
- /api/state 中 run_mode=sim、system_state=sim_ready、simulation.enabled=1、simulation.hardware_mode=0、emergency_stop=0。
- 已按用户要求停止该服务并释放其默认共享内存；隔离测试完成后没有遗留机器人仿真进程。
- 停止前未运行 `scripts/run-jetson-hardware.sh`，也未启动硬件模式。

停止仿真服务前的页面状态：

- GET http://127.0.0.1:8080/control：200
- GET http://127.0.0.1:8081/sim：200

指定只读 API：

| API | 状态 | 说明 |
|---|---:|---|
| /api/state | 200 | 仿真就绪 |
| /api/readiness/attestation | 404 | 当前 Nano 版本未提供该精确路由 |
| /api/workflow/state | 404 | 当前 Nano 版本未提供该精确路由 |
| /api/workflow/self_check | 404 | 当前 Nano 版本未提供该精确路由 |
| /api/motion_plan/preview?side=left | 404 | 当前 Nano 版本未提供该精确路由 |
| /api/motion_plan/preview?side=right | 404 | 当前 Nano 版本未提供该精确路由 |
| /api/acupoints/latest | 200 | 返回离线数据 |
| /api/motion_test/points?side=left | 200 | ok=true |
| /api/motion_test/points?side=right | 200 | ok=true |

## 左右仿真

仅调用了允许的接口：

    POST /api/motion_test/simulate
    {"side":"left"}

    POST /api/motion_test/simulate
    {"side":"right"}

结果：

- 左侧：200，26/26 点通过，result=all_points_passed，simulation_only=true，motor_command_written=false。
- 右侧：200，26/26 点通过，result=all_points_passed，simulation_only=true，motor_command_written=false。

原始结果和全部 HTTP 响应保存在：

/home/zzq/PTR/therapy_robot/docs/progress/evidence/nano-pretest/run-20260823-175851/

## 硬件边界核对

- 实体串口：未打开；只读检查未发现相关进程文件描述符。
- D405：未访问或启动；没有运行 RealSense/D405 程序。
- 进程文件描述符只读检查结果保存在 run-20260823-175851/hardware-fd-check.txt，没有匹配 /dev/tty 或 /dev/bus/usb 的句柄。
- 硬件模式：未启动。停止前的 main_motor 进程属于 run_mode=sim、hardware_mode=0 的既有仿真服务；当前已无该仿真进程。
- 电机命令：未生成。左右仿真响应均明确 motor_command_written=false。
- enable/disable/home/zero/jog/move/target/setpoint/brake release：均未调用。
- 正式 K0/K1/K2/K3/K4 标定、offset、软限位、碰撞边界和实体配置：未修改。
- scripts/run-jetson-hardware.sh：未运行。

## 仍存在的问题

1. 用户指定的 4 组 readiness/workflow/motion-plan 精确 GET 路径在当前版本返回 404，需要后续确认 API 版本或路径映射。
2. 当前报告只能证明仿真准备状态，不能证明实体硬件准备状态。

## 下一步需要明确批准的动作

如需修复 404 API，需要先明确当前仓库应采用的 API 路径/版本；这属于软件接口变更，不在本次部署准备中擅自修改。

本报告未访问串口、D405 或硬件控制入口。
