# H1 实体只读缺失字段

状态：`H1_EVIDENCE_INCOMPLETE`

以下字段在现有 10 次采样及其原始 `report.json`、`samples.jsonl`、`commands.log` 中未完整记录，不能从 `zzqVM` 仿真或软件测试补填：

- 实体设备身份：USB VID、USB PID、设备序列号、固件版本或等价可核验身份；
- 软件执行身份：检查时实际 Git commit（现有记录只有二进制 SHA-256）；
- 操作者、停止负责人和带时区的绝对检查时间；
- 实体串口实际路径（例如 `/dev/serial/by-id/...` 或明确的 `/dev/tty...`）；
- 采样开始前的串口占用者和端口状态；
- 是否存在虚拟机 USB/串口透传及其映射关系；
- K0 软限位下界、上界及单位；
- 急停状态；
- 看门狗状态/超时阈值/检查时状态；
- `motor_homed` 和 `motor_zeroed` 的独立状态字段；
- 原始命令审计中的绝对时间和设备路径关联。

已有但不能误读的字段：

- K0-K4 10 次连续反馈：已有；
- K0 `brake_state_known`、`brake_engaged`：已有；
- 在线、故障、使能、速度、反馈年龄：已有；
- `synthetic=false` 和 `entity_serial_accessed=true`：原始报告声明已有，但缺少可核验设备身份和路径；
- D405/运动/目标/使能声明：原始报告声明未发生，但不替代完整动作审计。

在字段补齐前，结论保持 `H1_EVIDENCE_INCOMPLETE`，不得填写 PASS。
