# PTR 理疗机器人软件

本仓库包含机械臂、视觉、离线仿真、审计和安全准备工具。

第一次接触项目，建议先阅读[仓库使用说明](docs/仓库使用说明.md)，了解项目组成、下载方式、协作上传流程和实体硬件边界。

## 当前状态

- B5 离线路线、视觉和演示闭环已集成。
- B6 软件安全基线、末端命令契约和末端离线仿真已集成。
- H1 软件预检已完成；实体 H1 只读检查等待连接 Nano 后单独执行。
- 默认不允许 Nano 部署、实体串口/D405 访问、电机使能、回零、置零或运动。

## 本地验证

```bash
python3 -m unittest discover -s tests/b4_prep -p 'test_*.py'
python3 -m unittest discover -s tests/b6 -p 'test_*.py'
python3 -m unittest discover -s tests -p 'test_*.py'
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python3 scripts/github_private_preflight.py --root .
```

首次私有上传见 [PUBLISHING.md](PUBLISHING.md)，协作规则见
[CONTRIBUTING.md](CONTRIBUTING.md)，敏感信息规则见 [SECURITY.md](SECURITY.md)。
