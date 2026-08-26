# S3 末端定位

S3 是 PTR 的末端定位离线验证模块，检查 IK 可达性、正式软限位、机箱碰撞路径、实际反馈误差和姿态误差。

第一次使用请阅读：

`S3-操作流程-小白版.md`

推荐顺序：编译 `build/s3-user`，运行 26 项 CTest，运行 14 点可达性矩阵，再用合成 CSV 运行 `endpoint_positioning_report`。

本目录只描述 zzqVM 软件离线验证：

```text
serial_accessed=false
d405_accessed=false
motor_command_generated=false
```

S3 不连接 Nano、不打开实体串口、不启动 D405、不使能电机，也不保证实体机械臂已经完成真实定位。
