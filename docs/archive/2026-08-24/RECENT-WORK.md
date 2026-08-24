# 近期工作归档（2026-08-24）

本归档记录 `therapy_robot` 在 2026-08-23 至 2026-08-24 的软件集成、证据归档和 GitHub 完整性检查。

## 环境身份

```text
host=zzqVM
address=192.168.216.129
architecture=x86_64
environment=virtual_machine
jetson_nano=false
```

`zzqVM` 不是 Jetson Nano。历史目录 `docs/progress/evidence/nano-pretest/` 是旧任务命名，内容只能证明
x86_64 虚拟机上的软件、仿真和离线验证，不能作为 Nano、ARM64 或实体运动 PASS 证据；当前实体只读 PASS 已由后续窗口单独记录。

## 归档基线

```text
repository=/home/zzq/PTR/therapy_robot
remote=git@github.com:159did/therapy_robot.git
source_main=57346c7f0209c2ecaa481e4843ebc9ac5ca90d1a
source_tree=993311a2f492e25455a75601faf061fc72ce0433
remote_main_at_audit=57346c7f0209c2ecaa481e4843ebc9ac5ca90d1a
```

## 近期已进入 main 的工作

| 提交 | 内容 |
|---|---|
| `3a1d16daca356d170326ccfef24975dbae909b9f` | B6 安全判定接入 B5 离线路线仿真入口 |
| `c00d7bc9ad285585279819af89663a4ee7027f57` | 合并 B7 仿真安全门 |
| `5669985ecb0d27bd984908faacffc2107c18e1d8` | readiness/workflow/motion-plan 只读 API 契约验证 |
| `d8f3cc4316627a4f66c5085955018ca60857dbc6` | 合并 B7 API 契约证据 |
| `57346c7f0209c2ecaa481e4843ebc9ac5ca90d1a` | 归档离线观察流和历史预检证据 |

## H1 分支状态

H1 审计分支已单独上传：

```text
branch=batch/h1-readonly-evidence
commit=ab75e1cf4e597fbf731d3a689063d463b25550bb
result=H1_ENTITY_READONLY_PASS
integrated_into_main=false
```

该审计确认保存的原始记录声称进行过实体只读采样，但缺少设备身份、操作者、绝对时间、源码提交、
串口路径、K0 软限位、急停、看门狗以及独立 home/zero 状态等必填字段。该历史窗口已被后续 H1 实体只读 PASS 窗口替代，
也不能据此授权实体运动。

## 验证结果

```text
git fsck --full --no-dangling: PASS
repository safety scan: PASS for private retention; publication_blocking=true
GitHub private push preflight: PASS
Python unittest: 79/79 PASS
Python py_compile: PASS
GitHub main remote readback: PASS
```

安全扫描发现仓库历史含实体标定/观察文件、机器本地硬件配置和采集样本。仓库必须保持私有；
未经脱敏和历史清理不得公开发布。

## 本地可恢复归档

```text
/home/zzq/PTR/backups/git-archive-20260824/therapy_robot-all-refs-20260824.bundle
SHA-256=a63542a8bde5e9631fab4006e5b528d71c11310d9b7a076fca8afac65e76c8ad
size=9956734 bytes

/home/zzq/PTR/backups/git-archive-20260824/therapy_robot-main-57346c7.tar.gz
SHA-256=18c0c471fcc086d909f61e2d8a1b2ba55c4f2f5dbb88541c6a86a9431106d312
size=10809817 bytes
```

Git bundle 已通过 `git bundle verify`，包含创建时可达的全部本地分支、远端跟踪引用和标签。
压缩包只包含 `source_main` 的跟踪工作树，不包含 `.git`、SSH 私钥、Token、密码或本机 `.env`。

## 关键文件 SHA-256

```text
22fbf40e27c79547a0356226bc9035d7ae913ec606e72e137fa9d5e0e2ca5283  scripts/b5/m1_m2_route_sim.py
e58ffe45222b8435262f3831016a8c755f279372ee60c8ec2445f81f16fb0402  tests/b5/test_m1_m2_route_sim.py
6dc19578e06d35622caaf83a5fca41f14b2e6779c65523648ed577b1de66d551  docs/progress/B7-SAFETY-GATE-INTEGRATION-SIM.md
d8ac7228db254c9ddff558b51ed3fcc45e43c655c8f4a4ab0e9be44f524ae955  docs/progress/B7-API-CONTRACT-CHECK.md
d687632e14750a1de124b11aba3df64bbd73653e43a4f545d3a2c91da385fcae  scripts/observation_flow.py
f4238005dad71bfbb386101fa8bdcf8ceaa8d85accfb82e5ebf79c612b068b72  tests/test_observation_flow.py
95e373362f94f05e1f4ff532a92ab17eae2f1ca431d1ae803d55cc0f4e8a9651  docs/progress/evidence/nano-pretest/REPORT-20260823.md
```

## 恢复说明

验证 bundle：

```bash
git bundle verify /home/zzq/PTR/backups/git-archive-20260824/therapy_robot-all-refs-20260824.bundle
```

从 bundle 创建独立恢复仓库：

```bash
git clone /home/zzq/PTR/backups/git-archive-20260824/therapy_robot-all-refs-20260824.bundle therapy_robot-recovered
```

不要在现有工作树上使用 `git reset --hard` 恢复。应先克隆到新目录、核对提交和文件，再决定如何迁移。

## 硬件边界

本归档和完整性检查没有访问实体串口或 D405，没有启动硬件模式，没有使能、回零、置零、移动电机，
也没有生成或发送实体电机命令。
\n\n当前统一规则：H1_ENTITY_READONLY_PASS 只表示实体反馈读取和未动作审计通过；execution_allowed=false、entity_action_authorized=false、entity_motion_authorized=false 继续保持，任何实体运动仍需单独授权。\n