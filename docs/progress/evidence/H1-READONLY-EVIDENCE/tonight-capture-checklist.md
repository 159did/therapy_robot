# 今晚 H1 实体只读补采清单

状态：`PREPARED_NOT_EXECUTED`

本清单只用于准备，不代表已经执行，也不授权实体运动。

## A. 执行前登记

- [ ] 记录操作者姓名/账号、停止负责人和带时区开始时间；
- [ ] 记录实体控制设备 hostname、IP、系统架构；
- [ ] 确认真实 Nano 与 `zzqVM` 分开，记录是否经过 VM USB/串口透传；
- [ ] 记录检查时软件 Git commit、二进制 SHA-256 和配置文件 SHA-256；
- [ ] 记录 `uname -m`、设备身份、USB VID/PID、序列号、固件版本；
- [ ] 列出 `/dev/serial/by-id/`、`/dev/tty*` 的实际映射；
- [ ] 记录每个实体串口的打开者、PID、占用状态和检查时间；

## B. 只读边界确认

- [ ] 只启动专用只读反馈程序；
- [ ] `THERAPY_ROBOT_READ_ONLY=1`；
- [ ] 不启动 Web 控制服务或自动轨迹；
- [ ] 不发送 enable、motor-on、brake-release、stop、home、zero、target、jog、move；
- [ ] 不访问 D405；
- [ ] 急停保持现有安全状态，不操作急停按钮作为测试动作；
- [ ] 抱闸保持当前状态，不发送松闸命令；

## C. 反馈采样

- [ ] 至少连续采样 10 次 K0-K4，建议间隔 100 ms 左右；
- [ ] 每次记录原始位置、offset、逻辑位置、SI 值、来源、有效性；
- [ ] 每次记录反馈序列、反馈时间、反馈年龄，明确单位；
- [ ] 每次记录 online、fault、enabled、速度、`feedback_error_state`；
- [ ] K0 单独记录 `brake_state_known`、`brake_engaged`；
- [ ] K0 记录软限位 lower/upper 和单位；
- [ ] 记录急停状态、看门狗状态和看门狗剩余/超时信息；
- [ ] 保存原始逐样本 JSONL，不做覆盖或就地修正；

## D. 结束和封存

- [ ] 只读程序自然退出，不发送停止或电机关闭控制命令；
- [ ] 记录退出时间、串口释放结果和退出后端口占用；
- [ ] 保存 `report.json`、`samples.jsonl`、`commands.log`、程序日志和环境身份文件；
- [ ] 对全部原始文件计算 SHA-256，生成 manifest；
- [ ] 复核所有动作字段：`motor_enabled=false`、`motor_homed=false`、`motor_zeroed=false`、`motor_moved=false`、`motor_command_generated=false`、`d405_accessed=false`；
- [ ] 实体窗口已完成，当前结论为 `H1_ENTITY_READONLY_PASS`；本清单不再作为当前判定来源。
