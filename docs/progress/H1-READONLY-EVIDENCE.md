# H1-READONLY-EVIDENCE 进度

分支：`batch/h1-readonly-evidence`

工作树：`/home/zzq/PTR/worktrees/h1-readonly-evidence`

基线：`88e7cae85977eab33d427f20dc828c856b1a80b8`

## 结果

| 项目 | 状态 | 证据 |
|---|---|---|
| H1 实体只读记录检索 | 完成 | Git 历史、任务材料和 `docs/progress/evidence` 均已检索。 |
| 实体记录数量 | 0 | 未发现实体身份、端口占用、K0 连续样本、抱闸或真实反馈记录。 |
| H1 当前结论 | `PENDING_ENTITY_READ_ONLY` | `docs/tasks/B5-H1-RECORD.json`。 |
| 软件预检结论 | 可用但不等价实体 PASS | `B5-H1-RESULT.md` 为 `SOFTWARE_PASS_ENTITY_PENDING`；Nano 预检报告为 `SOFTWARE_BLOCKED`。 |
| 仿真/离线证据 | 已归档索引 | `docs/progress/evidence/H1-READONLY-EVIDENCE/manifest.json`。 |
| 安全边界 | 保持关闭 | 本次未访问 Nano、D405、串口、共享内存或电机。 |

## 已审阅文件

审阅了 B5-H1 申请单、预检说明、记录模板、结果文件、周六只读检查表、软件预检材料、B6 安全基线设备访问检查，以及 2026-08-23 Nano 预检和离线观察流证据。每个输入文件的 SHA-256、分类和摘要写入 manifest。

## 阻塞原因

```text
no_entity_h1_record_found
device_operator_and_time_not_specified
no_physical_k0_samples
no_physical_brake_or_feedback_record
software_or_simulation_evidence_cannot_promote_to_entity_pass
```

此外，Nano 预检报告记录的四个精确 readiness/workflow/motion-plan GET 路径返回 404；这属于软件接口版本问题，不能用仿真响应替代实体只读证据。

## 安全说明

本任务是证据整理，不是 H1 实体执行。没有生成新的控制请求，没有补填未知的实体字段，没有把仿真快照中的 K0/电机字段复制进实体记录，也没有改变任何正式标定、软限位、碰撞或权限状态。

## 2026-08-24 白天准备追加

当前正式状态保持：

```text
H1_CURRENT_STATUS=H1_EVIDENCE_INCOMPLETE
entity_motion_authorized=false
hardware_control_authorized=false
```

已完成的白天准备：

- 保留旧窗口 `entity-raw/pose-readout-19700101T023629Z-retry1/` 及其原始文件，不修改、不覆盖、不重命名；
- 对已有 10 次 K0 样本建立派生审阅 `10-sample-review.md` 和 `k0-10-sample-review.json`；
- 建立缺失字段清单 `missing-fields.md`；
- 建立今晚清单 `tonight-capture-checklist.md`；
- 建立新窗口模板目录 `new-entity-window-20260824/`，模板状态为 `PREPARED_NOT_EXECUTED`，没有预填实体数据或 PASS；
- 建立已有原始文件的 `existing-raw-sha256-manifest.json`；
- 完成当前分支源码静态审核，结果为 `NOT_APPROVED_FOR_ENTITY_USE`。

静态审核发现当前 `main_motor`/`run-jetson-hardware.sh` 没有可证明的只读守卫，包含 enable、stop、zero、恢复、目标和退出时停止/松闸/电机关闭路径；`scripts/b5_h1_preflight.py` 只做软件检查，不能采集实体反馈。因此，在专用只读采样程序或经源码证明的只读分支确认前，今晚不得运行当前实体控制程序补证。

本追加仍未访问实体 Nano、实体串口或 D405，也未生成任何实体动作。


## 2026-08-24 实体只读窗口追加

本窗口使用真实 Jetson Nano `jetsonorin@192.168.2.100`（hostname `ubuntu`，`aarch64`，L4T `R35.6.3`），操作者和急停负责人均为 `159did`。证据时间以控制端联网时钟 `2026-08-24T12:52:08.080Z` UTC 为准；Nano 本地时钟只作诊断信息。

独立只读采集器在 Nano 上单独编译并运行，未启动 `main_motor`、`main_control`、`main_core` 或硬件启动脚本。采集使用三个稳定路径：`/dev/serial/by-path/platform-3610000.xhci-usb-0:2.1:1.0-port0`、`...2.2...`、`...2.3...`（VID `1a86`、PID `7523`）。采集结束后进程退出，三条串口均无占用者。

窗口共保存 50 条原始 JSONL 记录，每个 K0-K4 各 10 条。动作审计确认未发送 enable、disable、stop、松闸、回零、置零、jog、move、target 或 setpoint；未生成电机命令或目标；未发生运动；未访问 D405；未修改配置。

K0 原始位置 `16057` native，经 `k0-last-logical-native.txt` 和 offset 得到逻辑位置 `43206` native、逻辑高度 `3.00041666667 mm`；软限位为 `0..4523124 native`（`0..314.1058333333333 mm`），当前在范围内。K1-K4 的 online、fault、enabled、velocity 和逻辑位置均已记录；K1-K4 抱闸状态无法由只读接口独立确认，记录为 `unknown`。

正式结论仍为：

```text
H1_CURRENT_STATUS=H1_EVIDENCE_INCOMPLETE
```

原因是 Nano 工程没有 Git 元数据、采集二进制与源码提交无法进行 Git 可核验匹配，且急停、看门狗、限位、碰撞、独立 homed/zeroed 状态缺少独立原始证据。不得据此升级为 `H1_ENTITY_READONLY_PASS`。

新窗口证据目录：`docs/progress/evidence/H1-READONLY-EVIDENCE/entity-raw/20260824T125208Z/`。

