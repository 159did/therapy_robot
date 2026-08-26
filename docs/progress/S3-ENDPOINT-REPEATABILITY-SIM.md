# S3 末端重复定位自动循环进度

状态：`SOFTWARE_SIMULATION_PASS`

- 分支：`work/s3-endpoint-positioning`
- 平台：`platform=x86_64_vm`、`host=zzqVM`
- 输入：用户自选点位 CSV；每个点固定 3 次。
- 循环：到点、稳定、读取模拟 K0-K4、FK、验收、返回模拟安全起点、再次到点。
- 状态机：正常完成为 `COMPLETE`；移动超时、稳定超时、反馈丢失和预检失败均为 `STOPPED`。
- 报告：逐次 CSV 和包含事件/每点统计的 JSON。
- 确定性：相同输入产生字节级相同的 JSON/CSV。
- 示例：2 个合成点，共 6 次，全部 accepted，最终返回模拟安全起点。
- 说明：合成反馈和结果只用于软件流程验证，不是实体重复定位精度。

安全边界：`nano_tested=false`、`arm64_tested=false`、`entity_hardware_tested=false`、`serial_accessed=false`、`d405_accessed=false`、`shared_memory_written=false`、`motor_target_generated=false`、`motor_command_generated=false`、`execution_allowed=false`、`entity_action_authorized=false`、`entity_motion_authorized=false`。

回滚：撤销本任务提交即可；本任务未修改正式实体配置、offset、软限位或碰撞边界。
