# B5-VISION 论文视觉结果说明

## 实验目的

本实验整理毕业课题简化版的离线视觉结果，展示从一张已有 RGB-D 背部样本到目标区域、穴位坐标、候选机器人坐标和仿真末端目标的最小闭环。所有结果均由 `offline_vision_pipeline.py` 离线生成，不依赖正在运行的相机或机器人进程。

## 输入

- RGB 图像：`data/d405_samples/back_20260617_212933_470/rgb.png`，640×480；
- 深度：同目录 `depth_z16.npy`，按 `meta.json` 的 `0.0001 m/unit` 转换；
- 内参：同目录 `meta.json`；
- 坐标变换：B3 候选外参 `camcand-7827ed89d1c259219537a4f6`，由 SHA-256 显式绑定，仅作候选仿真变换；
- 正式外参：`calibration/camera_to_base.json` 当前缺失，因此不允许正式用途。

## 输出与识别效果

正常阈值 `min-confidence=0.40` 下，管线输出 7 个固定背部穴位：大椎、肺俞-L/R、心俞-L/R、肾俞-L/R。目标区域框为 `[119, 0, 520, 479]`，区域置信度 `0.962`，深度覆盖率 `0.739`，中心深度 `0.3987 m`。7 个穴位坐标置信度范围为 `0.654–0.929`，每个点都输出 RGB 像素坐标、相机坐标、候选机器人坐标以及 `executable=false` 的仿真目标。

答辩图和表格位于本目录：

- `01_input_overview.png`：原始输入图和输入哈希；
- `02_target_region.png`：深度支持的背部/目标区域框；
- `03_acupoints_annotated.png`：7 个穴位名称、像素坐标和置信度；
- `04_normal_vs_blocked.png`：正常与低置信度阻塞对比；
- `acupoint_results.csv` / `acupoint_results.md`：穴位结果表；
- `normal_result.json`：正常完整管线输出；
- `low_confidence_result.json`：质量不足时的阻塞输出；
- `paper_results_summary.json`：结果文件清单、哈希和安全锁摘要。

## 正常与阻塞对比

同一输入提高到 `min-confidence=0.99` 后，7 个穴位全部产生 `low_confidence:<穴位>` 阻塞，另外产生 `target_region_confidence_below_minimum`。管线返回非零退出码 `2`，每个穴位的 `simulation_endpoint_target` 均为 `null`，不会生成仿真目标。该对比证明质量不足时进入 blocking，而不是把不可靠结果继续送入后续流程。

正式外参缺失的正常案例仍可用于离线候选坐标和论文展示，但输出保持 `formal_transform_valid=false`，并记录 `formal_extrinsics_missing`。它不代表正式标定完成。

## 为什么当前只允许仿真

候选外参不是正式外参，不能证明相机到机器人基座的实体几何关系已经通过独立测量、验证和提升审批。当前结果只表达软件坐标链是否工作，不包含碰撞路径、末端力控、人体移动监测、硬件急停和现场安全确认。因此：

```text
formal_use_allowed=false
promotion_locked=true
execution_allowed=false
```

仿真末端目标使用 `coordinate_frame=robot_base_candidate`，并且 `executable=false`。本任务没有生成电机命令、目标序号、速度、扭矩或发送接口调用。

## 离线与硬件边界

本实验只读取仓库样本、候选外参文件和 JSON 输出。`d405_accessed=false`、`camera_device_opened=false`、`nano_accessed=false`、`serial_accessed=false`、`motor_command_generated=false`。没有打开相机、访问 Nano 或串口，也没有使能、置零或移动电机。
