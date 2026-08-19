# PTR 理疗机器人软件

本仓库包含机械臂、视觉、离线仿真、审计和安全准备工具。

## 当前状态

- B4-PREP 软件准备已完成。
- B5-H1-PREP 正在准备第一次 K0 **只读**实体窗口。
- 默认不允许 Nano 部署、实体串口/D405 访问、电机使能/运动或真人接触。

## 本地验证

```bash
python3 -m unittest discover -s tests/b4_prep -p 'test_*.py'
python3 -m unittest discover -s tests -p 'test_b5_h1_preflight.py'
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

协作规则见 [CONTRIBUTING.md](CONTRIBUTING.md)，敏感信息规则见 [SECURITY.md](SECURITY.md)。
