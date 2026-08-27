# S3 末端定位

S3 是 PTR 的末端定位离线验证模块，检查 IK 可达性、正式软限位、机箱碰撞路径、实际反馈误差和姿态误差。

第一次使用请阅读：

`S3-操作流程-小白版.md`

推荐顺序：编译 `build/s3-user`，运行 27 项 CTest，运行 14 点可达性矩阵，再用合成 CSV 运行 `endpoint_positioning_report`。需要验证重复定位流程时，继续运行 `endpoint_repeatability_sim`：可以从 CSV 手动选择点位，通过 `--repetitions 1..100` 设置每点次数，并模拟“到点、反馈验收、随机退开 15 mm、返回目标、最终回模拟安全起点”。

详细说明：

- `S3-操作流程-小白版.md`：从编译到查看结果的完整操作步骤；
- `../S3-ENDPOINT-REPEATABILITY-SIM.md`：重复定位仿真的参数、状态机和输出字段。

本目录只描述 zzqVM 软件离线验证：

```text
serial_accessed=false
d405_accessed=false
motor_command_generated=false
```

S3 不连接 Nano、不打开实体串口、不启动 D405、不使能电机，也不保证实体机械臂已经完成真实定位。默认的 1 mm/1 度是软件验收阈值，不是对真实机械臂精度的保证；超过阈值时离线流程输出 `FAIL/STOPPED`，不会继续后续点位。
