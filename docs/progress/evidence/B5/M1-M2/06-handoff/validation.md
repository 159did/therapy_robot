# B5-M1/M2 软件仿真验证摘要

任务：毕业课题简化版 M1/M2 软件仿真
基线：`d8ad99a8270121eecad61f576710ee31d2b34a25`
验证环境：zzqVM，Python 3.12

## 验收结果

```text
M1/M2软件仿真：PASS
左路线：PASS
右路线：PASS
急停：PASS，FAIL_CLOSED
看门狗：PASS，FAIL_CLOSED
反馈丢失：PASS，FAIL_CLOSED
相同条件重复运行：PASS，simulation_id稳定
实体设备访问：否
```

## 实现边界

`scripts/b5/m1_m2_route_sim.py` 是 B4-PREP-C `m1_m2_motion_sim.py` 的适配层，不复制底层运动模型。B4 继续负责详细五动作路线、归一化速度/位移、停止距离、急停、看门狗和反馈丢失；B5 只将选定侧的轨迹映射成：

```text
SAFE_HIGH -> LEFT_CAMERA_POSITION -> SAFE_HIGH
SAFE_HIGH -> RIGHT_CAMERA_POSITION -> SAFE_HIGH
```

正常结果的 `final_pose=STOWED`。故障结果为 `status=FAIL_CLOSED`、`final_pose=STOPPED`，不产生恢复目标。

## 安全字段

```text
synthetic=true
promotion_locked=true
formal_use_allowed=false
execution_allowed=false
entity_action_authorized=false
nano_deployment_authorized=false
```

## 回滚

集成前回退本任务来源提交即可；B4-PREP-C、共享内存、电机、串口、部署和实体参数不受本任务影响。

## 实体状态

没有访问实体串口、Nano 或实体 D405；没有部署、使能、回零、置零、发送实体运动指令或启动机器人进程。H1 实体只读仍未完成。
