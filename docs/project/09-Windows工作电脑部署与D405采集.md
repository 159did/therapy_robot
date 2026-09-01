# Windows 工作电脑部署与 D405 采集

本文档说明如何在一台 Windows 工作电脑上使用本项目。Windows 电脑负责 Git 协作、D405 RGB-D 采集和离线视觉处理；Linux/WSL 或 Linux 虚拟机负责 C++ 仿真；Jetson Nano 才负责实体电机程序。Windows 电脑不会直接控制 Nano、电机或实体串口。

## 1. 电脑职责

| 环境 | 用途 | 是否接触实体电机 |
|---|---|---|
| Windows 工作电脑 | 下载源码、D405 RGB-D 采集、离线视觉、查看结果 | 否 |
| Ubuntu/WSL/Linux 虚拟机 | 编译 C++、运行仿真和 CTest | 否 |
| Jetson Nano ARM64 | 编译/运行实体硬件程序 | 只有明确授权时才是 |

Windows 自带“相机”应用不是 D405 的可靠预览工具。D405 的 RGB、深度和红外流由 RealSense SDK 管理，应使用本项目的 `scripts/capture_d405.py` 或 Intel RealSense Viewer。

## 2. 准备 Git 和 Python

安装 Git for Windows、Python 3.11 或 3.12（推荐 3.12），可选安装 VS Code。检查安装：

```powershell
git --version
py -3.12 --version
```

私有仓库需要 GitHub SSH 密钥。已有权限时克隆：

```powershell
git clone git@github.com:159did/therapy_robot.git
cd therapy_robot
git status
```

如果只做一次下载，也可以在 GitHub 网页下载 ZIP；协作开发必须使用 Git clone、branch、commit 和 push。

## 3. 安装 Windows 依赖

在工程根目录执行：

```powershell
py -3.12 -m venv .venv-d405
.\.venv-d405\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-windows-d405.txt
```

如果 PowerShell 禁止激活脚本，可以直接使用虚拟环境解释器：

```powershell
.\.venv-d405\Scripts\python.exe -m pip install -r requirements-windows-d405.txt
```

## 4. 检查 D405

插入 D405 后执行：

```powershell
python -c "import pyrealsense2 as rs; d=rs.context().query_devices(); print('devices=', len(d)); [print(x.get_info(rs.camera_info.name), x.get_info(rs.camera_info.serial_number)) for x in d]"
```

正常情况下会看到 `RealSense D405` 和设备序列号。Windows 设备管理器中也应看到 `Intel(R) RealSense(TM) Depth Camera 405` 且状态为设备运行正常。

不要用 Windows“相机”应用是否有画面来判断 D405 是否正常。该应用可能打开错误的 UVC/红外接口并显示空白。

## 5. 采集一组 RGB-D 数据

先做不打开设备的预检：

```powershell
python scripts\capture_d405.py
```

预检必须显示 `live=false`，这一步不会访问相机。确认需要采集后，显式使用 `--live`：

```powershell
python scripts\capture_d405.py `
  --live `
  --output data\d405_captures\latest `
  --width 640 `
  --height 480 `
  --fps 30 `
  --warmup-frames 30 `
  --timeout-ms 5000
```

如果电脑上连接了多台 RealSense，可增加 `--serial <序列号>`。成功后目录包含 `rgb.png`、`depth_z16.npy`、`meta.json` 和 `SHA256SUMS`。

## 6. 运行离线视觉

```powershell
python scripts\offline_vision_pipeline.py --help
```

按照帮助信息指定 RGB-D bundle、候选外参和输出文件。候选外参必须保持 `formal_use_allowed=false`、`promotion_locked=true`、`execution_allowed=false`。没有正式 `calibration\camera_to_base.json` 时，只能生成候选坐标用于仿真和检查，不能发送给实体机械臂。

## 7. 在 Windows 上做完整离线验证

Windows 不能保证原生编译本项目 C++ 程序。推荐使用 WSL2 或 Linux 虚拟机：

```bash
sudo apt update
sudo apt install -y git build-essential cmake python3 python3-pip
python3 -m pip install --user numpy opencv-python-headless pillow jsonschema
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

不要把 x86_64 Windows/VM 二进制直接复制到 Nano；Nano 需要 ARM64 构建。

## 8. 与控制界面的关系

`capture_d405.py` 是独立采集入口，不会自动把照片显示到机器人控制网页，也不会自动移动机械臂。当前流程是：

```text
D405 采集 RGB-D
→ 离线质量检查
→ 离线穴位/候选坐标
→ 仿真末端目标
```

相机到机器人正式外参、实体轴偏置和实体执行授权全部确认后，才可以另行开发实体视觉闭环。当前默认仍是 `execution_allowed=false`、`entity_action_authorized=false`。

## 9. 常见问题

### `No module named pyrealsense2`

```powershell
py -3.12 -m pip install --user pyrealsense2
```

### `No module named numpy` 或 `PIL`

```powershell
py -3.12 -m pip install --user numpy pillow
```

### 设备管理器正常，但 Windows 相机是空白

关闭其他相机软件，使用 RealSense SDK 采集命令或 RealSense Viewer。Windows 相机应用不支持可靠地选择 D405 的 RGB-D 流。

### `No device connected` 或超时

更换 USB 3.x 端口和数据线，避免 USB 集线器，关闭 RealSense Viewer/其他占用程序后重试。

### 图像旋转 90 度

这是相机物理安装方向问题，不是采集失败。调整 D405 安装方向，或在离线视觉入口统一旋转图像，并记录旋转约定。

### 采集成功但不能控制机械臂

这是预期行为。采集程序没有串口和电机权限；正式外参、实体偏置和实体执行授权仍是独立门槛。

## 10. 验收记录

部署后至少保存 Windows 主机名、Python 版本、pyrealsense2 版本、D405 序列号、分辨率、帧率、输出目录和 `SHA256SUMS`。真实相机采集结果不要直接提交到公开仓库，仍应遵守 `SECURITY.md`。
