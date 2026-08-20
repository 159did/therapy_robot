# B5-H1 周六实体只读检查表

基线：`0e65a84`
范围：只确认 Nano、串口和当前反馈状态；不启动硬件控制路径，不发送任何改变状态的请求。

## 0. 进入窗口前的硬性条件

- 设备、操作者、急停负责人和现场时间已填写到 `docs/tasks/B5-H1-APPLICATION.md`。
- 软件工作树干净，`scripts/b5_h1_preflight.py` 为 `valid=true`。
- 先确认设备电源、机械臂支撑和急停位置；任何人可以立即断电/急停。
- 本窗口不得运行 `scripts/run-jetson-hardware.sh`：该脚本会打开 G0/G1/G2 串口，且 `THERAPY_ROBOT_AUTO_ZERO_ON_START` 默认是 `1`。

## 1. 只读记录字段

### A. Nano/软件身份

记录以下原始值，不修改文件：

```text
host_name
kernel_release
jetson_release_or_model
software_commit
git_worktree_clean
checked_at
```

`software_commit` 使用当前仓库提交号；`jetson_release_or_model` 只记录系统已经显示的型号/发行版信息，不安装包、不升级、不部署。

### B. 串口设备映射（只看，不打开）

仓库硬件配置对应三组总线：

| 字段 | 默认值/来源 | 必须记录 |
|---|---|---|
| `G0_port_configured` | `THERAPY_ROBOT_G0_PORT` 或 `/dev/ttyUSB0` | 配置路径 |
| `G1_port_configured` | `THERAPY_ROBOT_G1_PORT` 或 `/dev/ttyUSB1` | 配置路径 |
| `G2_port_configured` | `THERAPY_ROBOT_G2_PORT` 或 `/dev/ttyUSB2` | 配置路径 |
| `G0_port_resolved` | 解析符号链接后的路径 | 实际目标 |
| `G1_port_resolved` | 解析符号链接后的路径 | 实际目标 |
| `G2_port_resolved` | 解析符号链接后的路径 | 实际目标 |
| `stable_by_id_listing` | `/dev/serial/by-id/` | 设备名、厂商 ID、序列号 |
| `tty_listing` | `/dev/ttyUSB*`、`/dev/ttyACM*` | 节点、权限、时间 |
| `port_owner` | 仅查询占用者 | 必须为空；有占用立即 BLOCKED |

端口缺失、多个设备无法区分、路径与配置不一致或被其他进程占用，结论均为 `BLOCKED`。不要通过试开串口来“确认”设备。

### C. `/api/state` 只读快照（仅在已有只读状态服务且未触发硬件启动时）

若现场已有明确授权的状态服务，只允许 `GET /api/state`，保存原始 JSON；重点记录：

```text
emergency_stop
simulation.enabled
simulation.hardware_mode
control.heartbeat_ms
control.limit_alarm
control.collision.{configured,enabled,alarm,status,last_error}
axis_map[K0].{name,gui_display_unit,min_motor_native,max_motor_native}
groups[G0..G2].{port,last_error,hardware_enabled}
groups[*].motors[*].{
  configured,motor_id,axis,online,enabled,fault,mode,
  brake_supported,brake_engaged,brake_release_requested,
  brake_state_known,brake_last_error,
  actual_motor_native,target_motor_native,active_target_motor_native,
  actual_axis_si,target_axis_si,actual_motor_native_velocity,actual_current_a
}
```

H1 只读的 K0 结论至少包含：

```text
k0_actual_position_or_height
k0_soft_limit_min
k0_soft_limit_max
k0_online
k0_fault
k0_enabled
k0_brake_state_known
k0_brake_engaged
k0_feedback_stable
k0_observation_start/end
```

`target_*` 字段只用于发现是否已有目标，不得写入或修改；若目标与实际位置持续变化、反馈丢失、故障非零、抱闸未知或使能为真，立即 `BLOCKED`。

## 2. 明确禁止的动作

- 不运行 `run-jetson-hardware.sh`、`main_motor`、部署脚本或任何会打开实体串口的程序。
- 不执行串口读写、握手、探测帧、清缓存或改变波特率；不把 `/dev/ttyUSB*` 当作“测试一下”来打开。
- 不调用任何 `POST/PUT/PATCH/DELETE` 接口，包括 `enable_all`、`clear_faults`、回零/置零、jog、目标写入、运动序列、停止/恢复等控制接口。
- 不修改 `THERAPY_ROBOT_AUTO_ZERO_ON_START`、`ALLOW_ZERO`、offset、K0 限位、碰撞配置或任何正式标定。
- 不访问实体 D405，不采集照片/深度，不启动 Nano 部署，不生成电机目标，不使能、回零、置零或移动任何轴。

## 3. 结论规则与证据

只允许两种结论：

```text
PASS    设备身份明确；端口映射明确且无占用；K0 在线、无故障、未使能；
        软限位和抱闸状态已知；反馈在观察窗口内稳定；没有任何非只读动作。
BLOCKED 任一字段未知/矛盾，端口被占用，反馈丢失，故障非零，抱闸未知，
        急停不可用，或发生任何非只读请求。
```

证据只保存：原始身份输出、端口目录清单、只读状态 JSON（如有）、时间和软件提交号。将摘要写入 `docs/tasks/B5-H1-RECORD.json`，实体串口、D405、电机相关标志保持真实值；本次未执行前不得填写为已访问或 PASS。
