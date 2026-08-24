# H1 实体只读证据审核

结论：`H1_EVIDENCE_INCOMPLETE`

本审核严格区分软件运行主机和实体机器人控制设备。`zzq@192.168.216.129` 的主机名为 `zzqVM`，架构为 `x86_64`，只能作为虚拟机软件仓库/审核环境；不能把它的仿真、共享内存、HTTP API 或测试结果当作实体 H1 样本。

## 实际执行环境

| 项目 | 审核结论 |
|---|---|
| 软件/审核主机 | `zzqVM` (`192.168.216.129`)，Ubuntu 24.04，`x86_64`；非 Jetson Nano |
| 软件仓库 | `/home/zzq/PTR/therapy_robot` |
| H1 worktree | `/home/zzq/PTR/worktrees/h1-readonly-evidence` |
| H1 分支 | `batch/h1-readonly-evidence` |
| 证据中声称的实体设备 | `jetsonorin@192.168.2.100`，hostname `ubuntu`；原始 README 标为 Nano |
| 真实 Nano 是否参与 | 原始 `report.json` 的 `synthetic=false`、`entity_serial_accessed=true` 声称参与；本次无法重新连接确认 |
| 是否使用 VM USB/串口透传 | 未记录，无法证明 |
| 实体串口实际路径 | 未记录；只记录了结束后没有残留 `ttyUSB` 进程 |
| 操作者 | 未记录 |
| 绝对检查时间 | 未记录；目录名 `19700101...` 受设备时钟影响，不能当作检查时间 |

## 原始实体记录中确实存在的内容

- `report.json` 标记 `synthetic=false`、`entity_serial_accessed=true`、`d405_accessed=false`。
- K0-K4 连续采样 10 次；K0 具有 `feedback_position_native`、`actual_motor_native`、`actual_axis_si`、`feedback_time_ms`、`feedback_age_ms`、online/fault/enabled/velocity 和抱闸字段。
- K0 逻辑值为 `43206 native`、`3.0004167 mm`，来源 `k0_persisted_session`，`brake_state_known=1`，`brake_engaged=1`。
- 原始记录声明未使能、未松闸、未回零/置零、未发送目标、未运动，且 `d405_accessed=false`。
- `commands.log` 记录只读进程启动、共享内存名、PID、SIGTERM 退出和共享内存清理；它没有设备路径、操作者或绝对时间。

## 不能据此认定 H1_ENTITY_READONLY_PASS 的缺口

以下强制字段在原始实体证据中缺失，不能从 VM 仿真或软件测试补造：

- 实体设备 USB VID/PID、设备序列号、固件版本或其他可核验身份；
- 实体串口的实际路径和检查时端口占用清单；
- 操作者和带时区的检查时间；
- 检查时使用的源码 Git 提交号（仅有二进制 SHA-256）；
- K0 软限位下界/上界及单位；
- 急停状态；
- 看门狗状态；
- `motor_homed` 和 `motor_zeroed` 的独立状态字段（只有无相关命令的过程记录）。

因此本记录只能证明“保存的原始文件声称进行过一次 Nano 只读采样”，不能证明满足完整 H1 实体验收清单。

## 动作边界（按原始记录声明）

```text
motor_enabled=false
motor_homed=false       # 原始过程无 home 命令；独立状态未采样
motor_zeroed=false      # 原始过程无 zero 命令；独立状态未采样
motor_moved=false
motor_command_generated=false
d405_accessed=false
```

本次审核没有连接真实 Nano，没有访问实体串口，没有使能、回零、置零或移动电机，也没有访问 D405。

## 证据哈希

原始副本目录：`docs/progress/evidence/H1-READONLY-EVIDENCE/entity-raw/pose-readout-19700101T023629Z-retry1/`

该目录中的 `report.json`、`samples.jsonl`、`commands.log`、`main_motor.log`、`main_core.log`、`README.md` 与审核时保留的原始副本逐文件计算 SHA-256；具体值见同目录 `raw-sha256.txt` 和 `audit.json`。

历史 `PENDING` 文件保留不改写；本审核只新增实体原始副本和审计结论。
