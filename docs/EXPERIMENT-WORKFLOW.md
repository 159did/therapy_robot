# 实验工作流使用说明

这套入口把“高位准备、侧面路线、相机数据、穴位、末端候选目标、撤回和返回高位”统一成一个可复现报告。它同时支持两种边界：

- `offline`：使用已验证的路线 JSON 和视觉 JSON，生成完整仿真报告，不访问任何设备；
- `hardware`：当前有意阻断，必须先完成 H1 实体只读和控制门授权，不能靠参数绕过。

## 1. D405 采集

只检查脚本和依赖，不打开相机：

```bash
python3 scripts/capture_d405.py
```

明确要求采集一帧时才使用：

```bash
python3 scripts/capture_d405.py --live \
  --serial <D405_SERIAL> \
  --output data/d405_captures/<timestamp>
```

`--live` 只打开 D405，保存 `rgb.png`、`depth_z16.npy`、`meta.json` 和
`SHA256SUMS`。它不会打开实体串口、共享内存或电机服务。Nano 上必须先确认
`pyrealsense2`、RGB-D 分辨率、深度比例和相机序列号。

## 2. 离线视觉

采集包可交给已有的离线视觉管线。候选外参必须显式哈希绑定，正式外参缺失时仍保持不可执行：

```bash
python3 scripts/offline_vision_pipeline.py \
  --image data/d405_captures/<timestamp>/rgb.png \
  --depth data/d405_captures/<timestamp>/depth_z16.npy \
  --meta data/d405_captures/<timestamp>/meta.json \
  --candidate-extrinsics calibration/camera_to_base_candidate.json \
  --expected-extrinsics-sha256 <sha256> \
  --out /tmp/therapy_robot/vision.json
```

## 3. 完整离线工作流

使用已经通过 B5 M1/M2 和 VISION 校验的输入：

```bash
python3 scripts/experiment_workflow.py \
  --route docs/progress/evidence/B5/DEMO/route-right-from-b5-m1-m2.json \
  --vision docs/progress/evidence/B5/DEMO/vision-from-b5-vision.json \
  --side right \
  --mode offline \
  --output /tmp/therapy_robot/experiment-right.json
```

预期报告状态：

```text
BOOT -> SAFE_HIGH -> SIDE_ROTATED -> ARM_EXTENDED -> CAMERA_CAPTURED
-> ACUPOINTS_READ -> HOVER_TARGET -> HOLD_NO_CONTACT -> RETRACTED
-> RETURN_HIGH -> COMPLETE
```

报告中的候选末端位置是仿真数据，`executable=false`，不代表实体目标已经批准。

## 4. 实体模式

当前执行：

```bash
python3 scripts/experiment_workflow.py ... --mode hardware
```

会返回 `hardware_execution_requires_h1_and_central_gate`。这是预期行为。要解除阻断，后续必须完成：

1. H1 实体只读证据完整；
2. Nano、串口和控制板身份核验；
3. K0-K4 反馈、急停、看门狗、抱闸和软限位核验；
4. 低速、短距离、单轴、非接触实体测试；
5. 正式相机外参和 D405 质量验证；
6. 控制安全门在明确授权下放行。

本文件不授权电机动作，也不把离线报告当成实体通过证据。
