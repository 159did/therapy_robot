# B5-VISION 进度

基线：`d8ad99a8270121eecad61f576710ee31d2b34a25`
分支：`batch/b5-vision`
工作区：`/home/zzq/PTR/worktrees/b5-vision`
当前状态：论文视觉结果已整理；待集成
当前步骤：B5-VISION-PAPER-01 已完成

| 步骤 | 状态 | 证据 |
|---|---|---|
| B5-VISION-01 | 完成 | 正式 `camera_to_base.json` 缺失；B1/B2/B3 脚本和样本存在 |
| B5-VISION-02 | 完成 | RGB、depth、meta、SHA-256 和尺寸/有限值校验 |
| B5-VISION-03 | 完成 | 深度支持区域、7个穴位、相机坐标和坐标置信度 |
| B5-VISION-04 | 完成 | 候选外参哈希绑定、机器人候选坐标、不可执行仿真目标 |
| B5-VISION-05 | 完成 | B5 专项 9 项通过，含正常、已有样本、输入失败、外参失败和低置信度阻塞 |
| B5-VISION-06 | 完成 | B1/B2/B3 回归与 B5 共 28 项通过；示例和交付文档已完成 |
| B5-VISION-PAPER-01 | 完成 | 真实离线样本生成答辩图、正常/低置信度对比、CSV/Markdown 结果表和一页实验说明 |

## 测试结果

执行：

```text
python3 -m unittest -v \
  tests/test_calibration_tools.py \
  tests/test_d405_quality_gate.py \
  tests/test_camera_extrinsics_candidate.py \
  tests/test_offline_vision_pipeline.py
```

结果：`Ran 28 tests in 71.083s`，`OK`。其中 B1/B2/B3 回归 19 项，B5 专项 9 项。`py_compile`、`git diff --check` 均通过。

失败闭锁覆盖：

| 场景 | 预期结果 |
|---|---|
| 图片缺失 | 非零退出，`image_missing` |
| 图片尺寸错误 | 非零退出，`image_dimensions_invalid` |
| 深度缺失 | 非零退出，`depth_missing` |
| 候选外参缺失 | 非零退出，`candidate_extrinsics_missing` |
| 候选外参哈希不匹配 | 非零退出，`candidate_extrinsics_hash_mismatch` |
| 正式外参缺失 | 保持候选离线仿真，`formal_extrinsics_missing` 且正式使用锁定 |
| 识别置信度过低 | 非零退出，低置信度点的 `simulation_endpoint_target=null` |

## 真实离线样本证据

输入：`data/d405_samples/back_20260617_212933_470/{rgb.png,depth_z16.npy,meta.json}`。

- `pipeline_id=vision-9e2633f99c52a19fc0401a0e`
- 输出 SHA-256：`be04071f94aab72d91ea69294bf28bfc6f1f95d511b802f2da99402f31991c64`
- 图像 SHA-256：`c2f8ab41092c1a6f00867cd7970991c24b38692e94bf627c19b624596776b933`
- 候选外参 SHA-256：`9d1995e496f1e4a392eff487601b7f62693337c9d9f1fdb52acf53c8b038eebe`
- 目标区域：`bbox_px=[119,0,520,479]`，置信度 `0.9618325943537938`
- 穴位：7 个，坐标置信度范围 `0.6544796007503485` 至 `0.9287507626410911`
- 首个仿真目标（大椎）：`position_m=[0.1609163181992805,0.1728330895391088,1.2935009362530452]`
- `pipeline_valid=true`，`offline_simulation_valid=true`
- `formal_transform_valid=false`，`formal_blocking_reasons=[formal_extrinsics_missing]`

## 安全状态

- `formal_use_allowed=false`
- `promotion_locked=true`
- `execution_allowed=false`
- `entity_action_authorized=false`
- `nano_deployment_authorized=false`
- `d405_accessed=false`
- `camera_device_opened=false`
- `nano_accessed=false`
- `serial_accessed=false`
- `motor_command_generated=false`

本任务只读取离线文件；实体 D405、相机设备、Nano、串口和电机均未访问。未修改或生成正式外参，未生成可由电机直接消费的控制命令。

## 集成说明

状态为“待集成”。候选机器人坐标和仿真末端目标仅允许离线软件验证；正式外参经独立流程批准前，不得解除任何锁定字段。提交号由本次交付回执记录。

## 论文视觉结果证据

结果目录：`docs/tasks/B5-VISION-PAPER-RESULTS/`；实验说明：`docs/tasks/B5-VISION-PAPER-RESULTS.md`。

- 正常管线：`pipeline_id=vision-9e2633f99c52a19fc0401a0e`，7 个穴位，`pipeline_valid=true`；
- 低置信度管线：`pipeline_id=vision-4e3638070b809eb64698bb7e`，`pipeline_valid=false`，退出码 `2`；
- 低置信度阻塞原因：7 个 `low_confidence:<穴位>` 加 `target_region_confidence_below_minimum`；
- 低置信度输出没有任何 `simulation_endpoint_target`；
- 正常和阻塞输出均保留 `formal_use_allowed=false`、`promotion_locked=true`、`execution_allowed=false`；
- 图像 SHA-256：`c2f8ab41092c1a6f00867cd7970991c24b38692e94bf627c19b624596776b933`；
- 可视化生成器专项测试：`Ran 2 tests ... OK`；
- 已逐图检查 4 张 PNG，分辨率为 1600×980，标签、状态和安全说明无重叠。
