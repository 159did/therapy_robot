# S3 末端重复定位自动循环（纯软件仿真）

## 用途与边界

本工具验证完整自动循环：选择点位 -> 移动到点 -> 等待稳定 -> 读取模拟 K0-K4 反馈 -> 计算实际末端 Pose -> 返回模拟安全起点 -> 再次到点。每个点固定执行 3 次，结束后输出逐次 CSV 表格和 JSON 汇总。

这不是实体控制程序。它不访问 Nano、串口或 D405，不写共享内存，不生成电机 target、串口 payload 或电机命令。`SIMULATED_SAFE_START` 是软件测试起点，不是正式 K0-K1-K2-K3-K4 标定，也不是实体 SAFE_HIGH。

## 选择点位

复制示例文件并编辑：

```bash
cp tests/fixtures/endpoint_positioning/repeatability_points.csv /tmp/my-points.csv
```

一行代表一个点，可以增加或删除行；程序会对每一行执行 3 次：

```csv
point_id,target_x_m,target_y_m,target_z_m,target_rx_rad,target_ry_rad,target_rz_rad
left_15,-0.0600460185,0.224094792,0.79,0,0,0
right_15,0.0600460185,0.224094792,0.79,0,0,0
```

- XYZ 单位为 m；姿态单位为 rad。
- `point_id` 必须非空且不能重复。
- 每个点必须通过 IK、正式软限位、required collision config、起点检查和整段路径碰撞检查。
- 点位与模拟安全起点必须至少相距 0.010 m，确保每次测量后真的移开。
- 不可达、越限、碰撞或格式错误的点不会被模拟执行。

## 运行

```bash
cmake -S . -B build/s3-offline \
  -DBUILD_TESTING=ON \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/s3-offline --parallel 2

mkdir -p /tmp/s3-repeatability-result
build/s3-offline/endpoint_repeatability_sim \
  --points /tmp/my-points.csv \
  --collision-config config/enclosure-collision.csv \
  --json /tmp/s3-repeatability-result/report.json \
  --csv /tmp/s3-repeatability-result/table.csv
```

返回码：`0` 表示所有点各 3 次均完成；`1` 表示预检、超时、反馈或误差检查失败并停止；`2` 表示参数或点位 CSV 格式错误。

## 状态流程

```text
READY
  -> MOVING_TO_TARGET
  -> WAITING_TARGET_SETTLE
  -> CAPTURING_FEEDBACK
  -> RETREATING (返回 SIMULATED_SAFE_START)
  -> WAITING_RETREAT_SETTLE
  -> 下一次 MOVING_TO_TARGET
  -> 每点完成 3 次
  -> RETURNING_SAFE
  -> COMPLETE
```

任一移动超时、稳定超时、反馈丢失、IK、软限位、碰撞或误差检查失败都会进入 `STOPPED`，不会继续后续点位。

## 输出表格

CSV 每次测试一行，包含点位、重复序号、首次到达/移开后返回、目标 Pose、模拟 K0-K4 反馈、FK 实际 Pose、位置/姿态误差、阈值判定、移动/稳定耗时、反馈有效性、移开完成和硬件未访问字段。

JSON 额外包含完整状态事件和每点汇总：平均实际 XYZ、平均/最大/RMS 位置误差、平均/最大/RMS 重复性误差及重复性标准差。

纯仿真示例：

- `docs/tasks/S3-ENDPOINT-REPEATABILITY-SIM.example.csv`
- `docs/tasks/S3-ENDPOINT-REPEATABILITY-SIM.example.json`
