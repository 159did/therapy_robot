# H1 独立实体只读采集器

`h1_readonly_collector` 是独立于 `main_motor`、`main_control` 和 Web 服务的
C++ 程序。它不使用共享内存，只调用 MF9025V2 驱动的以下读取方法：

- `0x92` 多圈位置：`read_position`
- `0x9c` 状态：`read_status`
- `0x9a` 电机状态/故障：`read_state`
- K0 `0x8c/0x10` 抱闸读取：`read_brake`

编码器读取不作为 H1 必填项；部分控制器返回长度与旧驱动声明不一致，因此当前
采集器将 `encoder` 标记为 `null`，避免把不兼容响应误判为位置反馈。

源码中没有 enable、disable、stop、zero、jog、move、target、setpoint 或
松闸调用。程序启动前强制要求三个 `/dev/serial/by-path/` 路径，避免
`/dev/ttyUSB*` 枚举变化导致总线错配。

## 构建

```bash
cmake -S . -B build/h1-collector -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON
cmake --build build/h1-collector --target h1_readonly_collector --parallel 2
```

## 使用

控制端每次连接先获取网络 UTC 时间，再作为参数传入。示例：

```bash
./build/h1-collector/h1_readonly_collector \
  --g0-port /dev/serial/by-path/platform-3610000.xhci-usb-0:2.1:1.0-port0 \
  --g1-port /dev/serial/by-path/platform-3610000.xhci-usb-0:2.2:1.0-port0 \
  --g2-port /dev/serial/by-path/platform-3610000.xhci-usb-0:2.3:1.0-port0 \
  --offsets-file /home/jetsonorin/Documents/therapy_robot/config/axis-offsets-native.txt \
  --k0-file /home/jetsonorin/Documents/therapy_robot/config/k0-last-logical-native.txt \
  --controller-time-utc 2026-08-24T12:30:00.000Z \
  --samples 10 --interval-ms 100 \
  --output /tmp/h1-samples.jsonl
```

输出为一行一个轴样本的 JSONL。K0 使用 `k0-last-logical-native.txt` 重建逻辑
位置；K1-K4 使用 `axis-offsets-native.txt`。如果偏置文件缺失、串口路径不是
`by-path`、任一只读请求失败，程序以非零状态退出，不输出 PASS。

## 实体边界

当前只完成 VM 构建和源码审计，尚未把采集器部署到 Nano，也没有打开实体串口。
部署前必须重新核对 Nano 上的二进制 SHA-256、配置 SHA-256、三个串口稳定路径和
控制端时间。采集器本身不替代 H1 证据审计，不能自动把 H1 改成 PASS。
