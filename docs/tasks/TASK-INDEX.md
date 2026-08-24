# PTR 任务总表与编号规则

本文件是项目唯一的当前任务总表。所有人分配、开始、完成或集成任务前，先看本文件。

## 1. 编号规则

从 2026-08-24 起，新的工作只允许使用两类编号：

| 前缀 | 含义 | 例子 | 是否可以产生实体动作 |
| --- | --- | --- | --- |
| `S` | 软件工作：代码、仿真、数据处理、测试、集成 | `S3` 重复定位数据分析 | 否，除非另有 E 类现场批准 |
| `E` | 实验工作：需要回答的实验问题和对应数据 | `E3` 末端重复定位 | 由实验范围单独决定 |

以下旧编号不再用于创建新任务：

```text
B0-B8   历史开发批次
P*      停止使用
M*      停止使用
H1-*    停止拆分为子任务；H1 只归入 E2
G*      历史集成关口
```

历史编号、历史分支和历史文档不得删除、重命名或移动。它们只作为可追溯证据，在下表中通过“历史来源”引用。

## 2. 分支和文档规则

新分支只允许以下前缀：

```text
work/s<编号>-<短名称>
work/e<编号>-<短名称>
integration/<主题>
archive/<主题或日期>
```

示例：

```text
work/s3-repeatability-analysis
work/e3-endpoint-repeatability
integration/e2-e3
```

禁止新建 `batch/b*`、`batch/p*`、`execution/*`、`M*` 或 `H1-*` 类型分支。

文档规则：

- 当前状态只更新本文件和 `docs/EXPERIMENT-WORKFLOW.md`。
- 不为每个小任务新建 `docs/tasks/`、`docs/progress/` 或模板目录。
- 历史 `docs/tasks/`、`docs/progress/` 和 `docs/progress/evidence/` 保持原样。
- 只有发生真实实验时，才允许在现有 `docs/progress/evidence/` 下建立一个结果目录；该目录只保存原始数据、汇总结果和必要哈希，不保存重复任务说明。
- 任何新增任务先在本表登记，再创建分支；未登记不得开始。

## 3. 当前任务地图

### 软件线

| 编号 | 工作 | 状态 | 负责人 | 依赖 | 唯一下一步 |
| --- | --- | --- | --- | --- | --- |
| `S0` | 基础控制、运动学、只读 Web 和初始锁定 | 已完成，历史保留 | 历史 | 无 | 只修复明确缺陷，不扩展 |
| `S1` | 左右路线离线仿真与答辩材料 | 已完成 | 历史 | S0 | 作为 E1/E3 的离线预检来源 |
| `S2` | 集中软件安全门和 API 保护 | 已完成并集成 main | 2号/1号维护 | S0 | 只处理审查发现的 bug，不新增功能 |
| `S3` | 末端定位快速预检 | 待开始 | 同一名指定负责人 | S1、S2 | 完成目标预检、碰撞检查和反馈统计 |

### 实验线

| 编号 | 实验 | 状态 | 负责人 | 依赖 | 唯一下一步 |
| --- | --- | --- | --- | --- | --- |
| `E1` | 左右路线离线仿真与故障验证 | 已完成 | 历史 | S1 | 作为论文仿真结果使用 |
| `E2` | H1 实体只读确认：身份、反馈、无动作 | 完成，证据待并入 main | 1号 | S2 | 审查并合并 H1 证据分支；不授权运动 |
| `E3` | 给定末端目标的重复定位 | 待开始 | 与 S3 同一负责人 | S2、S3、E2 | 先做左右各 3 次快速验证；实体实验另行明确批准 |
| `E4` | 视觉/穴位离线处理 | 离线部分完成；实体视觉未开始 | 历史/后续可选 | S1 | 不阻塞 E3 |

## 4. 每项工作的定义

### S0: 基础控制、运动学和只读界面

已完成内容：五轴状态模型、运动学 FK/IK、Web 只读 API、接口契约、初始自动动作锁定和审计视图。

历史来源：

```text
batch/b0-infrastructure
batch/b1-auto-lock
batch/b1-frontend
batch/b1-offset
batch/b1-vision
batch/b2-workflow
batch/b2-workflow-frontend
batch/b2-motion-plan
batch/b2-vision-quality
batch/b3-audit-ui
batch/b3-camera-candidate
batch/b3-k0-prepare-sim
batch/b3-readiness-attestation
integration/g1
integration/g2
integration/g3
```

主线证据：

```text
docs/interface-contract.md
docs/software-validation.md
include/therapy_robot/kinematics.hpp
src/common/kinematics.cpp
tests/test_kinematics.cpp
```

### S1: 路线仿真和答辩材料

已完成内容：SAFE_HIGH 左右路线、低速/最小位移/停止距离的归一化仿真、急停/看门狗/反馈丢失 fail-closed、左右路线稳定性和离线答辩汇总。

历史来源：

```text
batch/b4-prep-a
batch/b4-prep-b
batch/b4-prep-c
batch/b4-prep-d
batch/b5-m1-m2
batch/b5-demo
batch/b5-defense-materials
integration/g4
integration/b5-offline-v1
integration/b5-offline-v2
```

主线证据：

```text
docs/progress/B5-M1-M2.md
docs/progress/B5-DEMO.md
docs/progress/evidence/B5/M1-M2/
docs/progress/evidence/B5/DEMO/
scripts/b5/m1_m2_route_sim.py
```

### S2: 集中软件安全门

已完成内容：实体 POST 入口统一默认拒绝、未知 API POST 默认拒绝、`main_control` 目标转换前检查、`main_motor` 串口初始化前和命令/目标消费前检查、SIMULATION 输出不生成实体命令。

历史来源：

```text
batch/b6-safety-baseline
batch/b6-ee-contract
batch/b6-ee-sim
batch/b7-api-contract-check
batch/b7-safety-gate-integration-sim
batch/b8-control-safety-gate-x86
batch/b8-vm-software-acceptance
batch/b8-low-speed-noncontact-prep
integration/b6-end-effector-foundation
integration/b8-agents-2-3-4
```

主线证据：

```text
docs/progress/B8-AGENTS-2-3-4-INTEGRATION.md
docs/progress/B8-CONTROL-SAFETY-GATE-X86.md
docs/progress/evidence/B8-AGENTS-2-3-4-INTEGRATION/
include/therapy_robot/control_safety_gate.hpp
src/common/control_safety_gate.cpp
tests/test_control_safety_gate.cpp
tests/test_control_safety_gate_api.py
```

### S3: 末端定位快速预检

目标：对每次到位后的实际 K0-K4 编码器反馈 `q_i` 使用现有 FK 计算末端估计位置 `P_i`，输出目标误差和重复定位误差。

固定范围：

```text
输入目标 T -> IK -> 到位实际反馈 q_i -> FK(q_i) -> P_i
目标误差：||P_i - T||
重复定位误差：||P_i - P_mean||
```

不做：单独 M0、单轴方向论文实验、D405 标定、自动连续实体运动或人体接触。

S3 最小完成条件：离线左、右目标各 3 条 fixture 能稳定生成 CSV、JSON 或表格，并完成 IK、软限位、碰撞预检和反馈统计；所有离线输出明确为仿真，不产生实体命令。每侧 10 条数据是论文扩展项，不是实体实验前置条件。

### E1: 左右路线离线仿真

已完成。结论限于软件仿真：左右路线在相同输入下稳定，急停、看门狗、反馈丢失均 fail-closed。

历史证据：

```text
docs/progress/evidence/B5/DEMO/nominal-left.json
docs/progress/evidence/B5/DEMO/nominal-right.json
docs/progress/evidence/B5/DEMO/route-watchdog-from-b5-m1-m2.json
docs/progress/evidence/B5/DEMO/verification.txt
```

### E2: H1 实体只读确认

范围固定为：

```text
identity_feedback_no_motion
```

结论固定为：

```text
H1_ENTITY_READONLY_PASS
entity_motion_authorized=false
hardware_control_authorized=false
```

E2 证明设备身份和只读反馈可用，并证明采样期间未产生运动命令；它不构成实体运动授权。

历史来源和待合并证据：

```text
branch: batch/h1-readonly-evidence
commit: 74a2b84842ca676b4369b30ea9891bd2900ebd35
docs/progress/H1-READONLY-EVIDENCE.md
docs/progress/evidence/H1-READONLY-EVIDENCE/entity-raw/20260824T125208Z/
docs/progress/evidence/H1-READONLY-EVIDENCE/entity-raw/20260824T125208Z/report.json
docs/progress/evidence/H1-READONLY-EVIDENCE/entity-raw/20260824T125208Z/samples.jsonl
```

### E3: 末端重复定位

快速落地目标：对一个左侧目标和一个右侧目标各重复 3 次。每次从 SAFE_HIGH 进入目标、到位后读取实际 K0-K4 反馈、计算 FK 末端估计位置、返回 SAFE_HIGH，并记录结果。快速验证稳定后，才考虑扩展到每侧 10 次作为论文数据。

E3 只由一名指定负责人完成记录和现场操作，1号只做一次安全复核和最终集成，不再拆分为“数据分析、现场记录、模板”三个并行角色。

E3 的最小现场流程：

```text
离线目标预检
-> 1号安全复核
-> 用户明确批准本次速度、位移和目标
-> 左侧 3 次：SAFE_HIGH -> 目标 -> 读取反馈 -> SAFE_HIGH
-> 右侧 3 次：SAFE_HIGH -> 目标 -> 读取反馈 -> SAFE_HIGH
-> 汇总误差并决定是否扩展到 10 次
```

任一次出现碰撞预警、软限位异常、反馈丢失、看门狗异常、急停或未回到 SAFE_HIGH，立即停止，不继续下一次。

E3 的论文结论只允许写为：

```text
基于实际编码器反馈与正运动学的末端估计重复定位性能。
```

不得把该结果写成未经外部测量验证的物理空间绝对精度。

实体 E3 在以下条件同时满足且用户单独批准前始终是 `NOT_STARTED`：

```text
E2=H1_ENTITY_READONLY_PASS
S2 集成并通过回归
S3 已完成
目标经过离线 IK/限位/碰撞预检
现场急停和人员隔离确认
本次速度、位移和目标由用户明确批准
```

### E4: 视觉/穴位离线处理

离线视觉、候选外参和论文材料已完成；真实 D405、正式外参和实体穴位执行不在当前主线，不阻塞 E3。

历史来源：

```text
batch/b5-vision
docs/progress/B5-VISION.md
docs/tasks/B5-VISION-PAPER-RESULTS.md
docs/tasks/B5-VISION-PAPER-RESULTS/
```

## 5. 负责人边界

| 角色 | 当前职责 | 不负责 |
| --- | --- | --- |
| 1号 | E2 证据归一、S/E 集成、一次安全复核 | 未经批准的实体动作 |
| 2号 | S2 安全门维护，只修复明确 bug | 新增实验路线或自动运动 |
| 指定负责人 | 同时完成 S3 离线预检、E3 左右各 3 次记录和结果汇总 | 修改标定、安全边界或绕过安全门 |

## 6. 状态更新规则

状态只能使用：

```text
NOT_STARTED
IN_PROGRESS
READY_FOR_REVIEW
COMPLETED
BLOCKED
```

规则：

1. 软件任务完成必须有 commit、测试命令和测试结果。
2. 实验任务完成必须有原始数据、汇总结果、时间、设备/平台身份和边界声明。
3. 仿真完成不能写成实体完成。
4. E2 通过不能写成实体运动授权。
5. 任何人开始新工作前先在本表添加一行，不创建新编号体系。
6. 1号集成时只更新本表中的状态、commit 和历史来源，不复制历史 evidence。

## 7. 当前唯一执行顺序

```text
E2 证据归一并集成
-> S3/E3 单负责人快速闭环（先离线预检，再左右各 3 次）
-> E3 扩展到每侧 10 次（可选，用户批准后）
-> E4 可选
```

除上述步骤外，不创建新批次、新阶段、新目录或新模板。
