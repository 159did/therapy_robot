# B5-VISION 毕业课题离线视觉闭环任务卡

任务ID：`B5-VISION`
基线：`d8ad99a8270121eecad61f576710ee31d2b34a25`
分支：`batch/b5-vision`
工作区：`/home/zzq/PTR/worktrees/b5-vision`
负责人：3号，视觉与标定泳道
状态：待集成

## 目标

复用 B1/B2/B3 的离线 RGB-D 样本、质量规则和候选外参模式，实现：读取照片和深度、定位背部/目标区域、生成穴位像素和相机坐标、使用显式哈希绑定的候选外参转换为机器人候选坐标，并生成不可执行的仿真末端目标。

## 允许修改

```text
scripts/offline_vision_pipeline.py
tests/test_offline_vision_pipeline.py
docs/tasks/B5-VISION.md
docs/tasks/B5-VISION-OUTPUT.example.json
docs/progress/B5-VISION.md
```

## 禁止事项

- 不访问实体 D405 或相机硬件；
- 不访问 Nano、实体串口、共享内存或电机；
- 不部署、不使能、不置零、不运动；
- 不修改或生成正式 `camera_to_base.json`；
- 不把候选外参当正式外参；
- 不生成可被电机消费的命令、序号、速度或扭矩。

## 冻结契约

输出 `schema_version=b5.vision-offline.v1`。候选外参必须是有效的 `b3.camera-extrinsics-candidate.v1`，显式 SHA-256 必须匹配，且 `formal_use_allowed=false`、`promotion_locked=true`、`execution_allowed=false`。仿真末端目标使用 `coordinate_frame=robot_base_candidate` 和 `executable=false`。

正式外参不存在不妨碍候选坐标的离线仿真，但必须写入 `formal_blocking_reasons=[formal_extrinsics_missing]`；候选外参缺失、哈希错误、输入/深度缺失、尺寸错误或置信度不足均非零退出。

## 验收步骤

| 编号 | 内容 | 状态 |
|---|---|---|
| B5-VISION-01 | 基线、现有工具、样本和正式外参盘点 | 完成 |
| B5-VISION-02 | RGB-D 输入、哈希和严格校验 | 完成 |
| B5-VISION-03 | 目标区域、穴位、置信度和相机坐标 | 完成 |
| B5-VISION-04 | 候选外参绑定、机器人候选坐标和仿真目标 | 完成 |
| B5-VISION-05 | 正常/缺失/尺寸/深度/外参/哈希/低置信度测试 | 完成 |
| B5-VISION-06 | 回归、示例、证据和提交 | 完成 |

## 交付物

- `scripts/offline_vision_pipeline.py`：离线 RGB-D 到仿真末端目标的最小闭环；
- `tests/test_offline_vision_pipeline.py`：正常样本和七类失败/安全场景；
- `docs/tasks/B5-VISION-OUTPUT.example.json`：锁定状态下的输出 JSON 示例；
- `docs/progress/B5-VISION.md`：真实离线样本、回归和安全证据。
