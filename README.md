# PTR 理疗机器人软件

本仓库包含机械臂、视觉、离线仿真、审计和安全准备工具。

第一次接触项目，建议先阅读[仓库使用说明](docs/仓库使用说明.md)，了解项目组成、下载方式、协作上传流程和实体硬件边界。

## 当前状态

- S1/E1 左右路线离线仿真、视觉离线处理和演示材料已完成。
- S2 集中式软件安全门、末端命令契约和离线仿真保护已完成并集成。
- E2/H1 按简化课题范围完成实体只读确认；范围仅为身份、反馈和无动作观察，不授权实体运动。
- 默认只允许软件和离线工作，不允许 Nano 部署、实体串口/D405 访问、电机使能、回零、置零或运动。

## 本地验证

```bash
python3 -m unittest discover -s tests/b4_prep -p 'test_*.py'
python3 -m unittest discover -s tests/b6 -p 'test_*.py'
python3 -m unittest discover -s tests -p 'test_*.py'
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python3 scripts/github_private_preflight.py --root .
```

## 协作任务规则

所有当前任务、负责人、状态、依赖和历史证据统一登记在
[`docs/tasks/TASK-INDEX.md`](docs/tasks/TASK-INDEX.md)。开始任何工作前先阅读该文件；完成每一步后，必须更新任务状态、测试结果和证据位置。

### 编号体系

从 2026-08-24 起只使用两条任务线：

- `S`：软件工作，包括代码、仿真、离线数据处理、测试和集成。
- `E`：实验工作，包括需要实际回答的实验问题和实验数据。

新的任务不得使用 `B*`、`P*`、`M*`、`H1-*` 或 `G*` 编号。这些编号属于历史记录，只能在任务总表中作为历史来源引用。历史分支、历史文档和历史证据不得为了改名而删除、移动或重写。

当前任务顺序为：

```text
E2 -> S3 -> E3
```

其中：

- `E2`：H1 实体只读确认，范围是身份、反馈和无动作观察，不授权实体运动。
- `S3`：基于实际 K0-K4 反馈和 FK 的末端重复定位数据分析，只做软件和离线验证。
- `E3`：末端重复定位实验，必须等 S3 完成并取得用户对实体动作的单独批准。

`S0`、`S1`、`S2`、`E1` 和 `E4` 的历史完成情况及证据位置见任务总表。

### 分支和文档

新分支只使用以下形式：

```text
work/s<编号>-<短名称>
work/e<编号>-<短名称>
integration/<主题>
archive/<主题或日期>
```

不要继续创建 `batch/*`、`execution/*` 或按小任务重复创建新的文档目录。当前状态只更新 `docs/tasks/TASK-INDEX.md` 和 `docs/EXPERIMENT-WORKFLOW.md`；真实实验产生的数据才放入现有 `docs/progress/evidence/` 目录。

每次完成任务时，回报至少包含：任务编号、分支、commit、修改文件、测试命令和结果、证据位置、未完成内容、下一步，以及硬件访问声明。

### 硬件边界

默认只允许软件和离线工作。没有用户明确批准时，不得：

- 访问 Nano、实体串口或 D405；
- 启动硬件模式或 `scripts/run-jetson-hardware.sh`；
- 使能、回零、置零、jog、move、target 或发送任何电机命令；
- 修改正式 K0-K4 标定、offset、软限位、碰撞边界或硬件配置。

虚拟机 `zzq@192.168.216.129` 是 x86_64 的 `zzqVM`，不是 Nano。虚拟机仿真证据必须明确标记为离线或 x86_64 VM，不能写成 Nano 或实体通过证据。

角色安排和统一完成回报格式见 [`docs/EXPERIMENT-WORKFLOW.md`](docs/EXPERIMENT-WORKFLOW.md)。

首次私有上传见 [PUBLISHING.md](PUBLISHING.md)，协作规则见
[CONTRIBUTING.md](CONTRIBUTING.md)，敏感信息规则见 [SECURITY.md](SECURITY.md)。
