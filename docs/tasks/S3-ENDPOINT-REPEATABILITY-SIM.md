# S3 末端重复定位自动循环（纯软件仿真）

## 用途与边界

本工具验证完整自动循环：选择点位 -> 移动到点 -> 等待稳定 -> 读取模拟 K0-K4 反馈 -> 计算实际末端 Pose -> 在目标周围随机退开 15 mm -> 再次返回目标。每个点固定执行 3 次，结束后输出逐次 CSV 表格和 JSON 汇总。

这不是实体控制程序。它不访问 Nano、串口或 D405，不写共享内存，不生成电机 target、串口 payload 或电机命令。`SIMULATED_SAFE_START` 只用于整个实验开始和最终结束，不参与每次局部重复定位；它不是正式 K0-K1-K2-K3-K4 标定，也不是实体 SAFE_HIGH。

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
- 不可达、越限、碰撞或格式错误的点不会被模拟执行。

## 随机局部退开

- 圆心为当前目标 Pose，平面固定为 `BASE_XY`。
- 默认半径为 `0.015 m`（15 mm），Z 与 RX/RY/RZ 保持目标值不变。
- `--random-seed` 控制确定性随机角度；相同输入与 seed 会得到字节级相同的 JSON/CSV。
- 候选点必须同时通过“实际反馈位置 -> 退开点”和“退开点 -> 目标点”的现有预检。预检覆盖 IK、正式软限位、required collision config、起点和整段路径碰撞检查。
- 默认最多尝试 36 个随机方向；全部失败时进入 `STOPPED`，原因为 `no_safe_random_retreat_point`。

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
  --retreat-radius-m 0.015 \
  --random-seed 20260827 \
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
  -> SELECTING_RANDOM_RETREAT
  -> RETREATING (目标周围 BASE_XY 圆周 15 mm 点)
  -> WAITING_RETREAT_SETTLE
  -> 下一次 MOVING_TO_TARGET（从随机退开点返回目标）
  -> 每点完成 3 次
  -> RETURNING_SAFE
  -> COMPLETE
```

任一移动超时、稳定超时、反馈丢失、IK、软限位、碰撞或误差检查失败都会进入 `STOPPED`，不会继续后续点位。

## 输出表格

CSV 每次测试一行，包含点位、重复序号、首次到达/移开后返回、目标 Pose、模拟 K0-K4 反馈、FK 实际 Pose、位置/姿态误差、阈值判定、移动/稳定耗时、随机 seed、角度、15 mm 退开 Pose、双向安全预检、移开完成和硬件未访问字段。

JSON 额外包含完整状态事件和每点汇总：平均实际 XYZ、平均/最大/RMS 位置误差、平均/最大/RMS 重复性误差及重复性标准差。

纯仿真示例：

- `docs/tasks/S3-ENDPOINT-REPEATABILITY-SIM.example.csv`
- `docs/tasks/S3-ENDPOINT-REPEATABILITY-SIM.example.json`
