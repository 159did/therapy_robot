# B8-LOW-SPEED-NONCONTACT-PREP

任务负责人：4 号
基线：`9e0c4b925062b0a7c8fd2fa25fd985fe9798402b`
分支：`batch/b8-low-speed-noncontact-prep`
工作树：`/home/zzq/PTR/worktrees/b8-low-speed-noncontact-prep`

## 结论

本任务只完成未来第一次实体低速、短距离、单轴、非接触实验的协议准备、检查表、记录模板和离线故障演练。当前 H1 状态为 `H1_EVIDENCE_INCOMPLETE`，因此本任务不产生实体 GO，不执行实体实验。

所有输出固定为：

```text
platform=x86_64_vm
simulation_only=true
nano_tested=false
arm64_tested=false
entity_experiment=not_run
hardware_authorized=false
entity_motion_authorized=false
```

未来实体参数全部保留为 `PLACEHOLDER_REQUIRES_APPROVAL`，没有填写真实速度、位移、轴、方向或停止距离，也没有生成原生单位、电机 setpoint、串口 payload 或可执行目标。

## 实验目标

在 H1 实体只读证据完成且 B8 安全门获批后，仅验证一次单轴、单个离散动作的低速短距离非接触行为。目标不是完成左/右路线、穴位序列或自动轨迹，而是确认一项经人工批准的最小动作能够在反馈、软限位、碰撞、急停、看门狗和抱闸状态均正常时被安全观察和记录。

“非接触”同时表示：不接触人体、不接触假人、不接触任何其他物体；活动空间内无人。

## 环境身份与参与角色

当前仅允许：

```text
platform=x86_64_vm
host=zzqVM (VM, not a real Nano)
software_commit=9e0c4b925062b0a7c8fd2fa25fd985fe9798402b
nano_commit=PLACEHOLDER_REQUIRES_APPROVAL
entity_device_identity=PLACEHOLDER_REQUIRES_APPROVAL
```

未来实体窗口必须有一名现场操作者、一名独立急停负责人和一名独立复核者。操作者和急停负责人不得由同一人兼任；三者的姓名、窗口时间、设备身份和授权单号必须在记录中填写后才能评估 GO。

## 前置条件

- H1 必须达到 `H1_ENTITY_READONLY_PASS`；当前为 `H1_EVIDENCE_INCOMPLETE`，所以本任务当前只能 `NO-GO`。
- B8 安全门必须集成并通过。
- 真实 Nano 的 ARM64 编译和只读状态证据必须存在；当前 `arm64_tested=false`、`nano_tested=false`。
- 急停可用、看门狗正常、反馈有效且未过期、软限位明确、碰撞状态正常、抱闸状态已知。
- 用户必须明确批准本次具体单步动作；授权不可泛化到后续动作。
- 单一执行代理、现场操作者和独立急停负责人在场，工作空间内无人。
- 每一步执行前重新读取安全状态并人工确认；每一步完成后立即停下并保存记录。

## 单步协议

1. 创建新的 `request_id`，核对窗口、设备、角色、提交号和批准范围。
2. 在执行前只读重读 H1、急停、看门狗、反馈、软限位、碰撞和抱闸状态。
3. 由操作者口头复述并由独立复核者确认：单轴、一个离散动作、非接触、活动区无人、没有自动序列。
4. 未来实体参数必须先获得批准；在批准前仍使用 `PLACEHOLDER_REQUIRES_APPROVAL`，不得从文档或历史配置猜测数值。
5. 未来窗口最多执行一个离散动作；禁止连续 jog、自动序列、完整左路线、完整右路线和穴位序列。
6. 动作完成后立即停止，保存原始状态、时间、request_id、授权号和 SHA-256；不自动进入下一步。
7. 任何异常立即停止并进入 `NO-GO`；恢复不能自动发生，必须新建 `request_id` 并重新授权、重新读取全部安全门。

## GO 条件

GO 只有在以下条件全部为 `true` 时成立：

- `H1_ENTITY_READONLY_PASS`；
- B8 安全门集成并通过；
- 真实 Nano ARM64 编译通过；
- Nano 只读状态通过；
- 急停可用；
- 看门狗正常；
- 反馈有效；
- 软限位明确；
- 碰撞状态正常；
- 抱闸状态已知；
- 用户明确批准本次具体动作；
- 单一执行代理；
- 现场无人；
- 操作者和急停负责人在场。

任一条件不满足就是 `NO-GO`。当前至少 H1、真实 Nano、ARM64、实体只读状态和用户具体动作批准不满足，因此当前结论固定为 `NO-GO`。

## NO-GO 与停止条件

以下任一情况必须立即停止，不允许自动恢复：反馈丢失、反馈过期、看门狗超时、软限位异常、碰撞状态异常、抱闸状态未知、急停不可用、人员进入工作空间、设备身份不匹配、授权过期、任何非只读请求或证据无法保存。

停止后保持实体运动授权为 `false`，保留故障前后原始证据；恢复必须使用新的 `request_id`、新的明确授权并重新检查全部 GO 条件。软件仿真中的 `NO_GO` 仅为故障演练结果，不代表实体急停已经触发。

## 回滚过程

当前准备阶段的回滚是：不启动硬件、不修改仓库实体参数、不改变正式标定/offset/软限位/碰撞边界、不发送目标、不恢复故障状态。未来实体窗口若进入异常：停止当前单步、保持电机关闭或由现场急停负责人执行物理急停，记录状态并撤销授权；任何重新尝试必须重新申请。

## 离线验证范围

复用现有 B4/B5/B6 纯软件模型和测试：

- B4 normalized 模型：最低速度边界、最小位移边界、停止距离和急停/看门狗/反馈丢失安全停止；
- B5 左右路线模型：左右输入重复运行稳定性、故障后 `FAIL_CLOSED`、不自动恢复；
- B6 安全基线：反馈丢失、反馈过期、看门狗超时、软限位异常、碰撞异常、权限不足和 H1 未通过均拒绝实体控制；
- B8 自身演练：急停不可用、反馈丢失/过期、看门狗、软限位、碰撞、抱闸未知、授权过期，以及正常准备仍保持 `go=false`。

所有离线数据为 normalized fixture、仿真状态或 placeholder；没有真实动作数值。日志位置：`docs/progress/evidence/B8-LOW-SPEED-NONCONTACT/`。

## 原始日志与 SHA-256

本任务生成的离线测试日志、命令输出和文件哈希写入：

```text
docs/progress/evidence/B8-LOW-SPEED-NONCONTACT/
```

协议正文使用 `source_sha256` 绑定；篡改、未知字段、NaN/Infinity、真实参数替换或安全政策解锁均失败关闭。完整清单见进度文件。

## 实验结论

当前为 `PREPARATION_ONLY / NO-GO`。没有访问 Nano、串口或 D405，没有启动硬件模式，没有使能、disable、回零、置零、jog、move、松闸或发送 target，没有生成原生电机 setpoint。下一步只有在用户明确批准具体实体窗口、完成 H1 实体只读证据、确认真实 Nano/ARM64 和全套 GO 条件后，才能另行执行实体准备审查；本分支本身不执行实体动作。
