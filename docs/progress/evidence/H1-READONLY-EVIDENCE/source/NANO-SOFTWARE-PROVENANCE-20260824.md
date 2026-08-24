# Nano 软件版本追溯记录（2026-08-24）

## 当前结论

- Nano：`jetsonorin@192.168.2.100`，hostname `ubuntu`，架构 `aarch64`。
- 当前部署目录与备份 `data/backup/h1-readonly-preflight-20260824T124721Z/` 的 bin/config 文件逐项 SHA-256 一致。
- 这证明当前部署快照没有偏离该备份；由于 Nano 工程没有 `.git`，不能仅凭备份反推出原始 Git commit。
- H1 证据时间使用控制端联网时钟；Nano 本地时间只作诊断。

## 已核验内容

| 范围 | 结果 |
|---|---|
| `bin/main_core` | 当前与备份一致 |
| `bin/main_control` | 当前与备份一致 |
| `bin/main_motor` | 当前与备份一致 |
| `bin/main_sim` | 当前与备份一致 |
| `bin/main_web_control` | 当前与备份一致 |
| `bin/main_web_sim` | 当前与备份一致 |
| `config/axis-offsets-native.txt` | 当前与备份一致 |
| `config/k0-last-logical-native.txt` | 当前与备份一致 |
| `config/enclosure-collision.csv` | 当前与备份一致 |
| `config/jetson-hardware.env` | 当前与备份一致 |

## 今日独立只读采集器

- 源码仓库：`git@github.com:159did/therapy_robot.git`
- 源码提交：`192d9c697f314b20c4b8e86ed9883f79c1ea6ff3`
- 采集器源码 SHA-256：`ff1f6c0a523e0ec742dd39c2f5516aac84200b7a9ecfe719f4839e9eba460152`
- 采集器二进制 SHA-256：`cc1186d928219248ce0d27a46096b562f9d9957a8c9025f103da555d23dab03a`
- 采集器只在 Nano `/tmp` 临时目录编译运行，没有覆盖正式 `bin`。

## 后续强制记录格式

每次向 Nano 同步或编译前，必须保存：

1. 控制端联网时间（UTC）；
2. zzqVM 源码仓库和 Git commit；
3. 要同步文件的 SHA-256；
4. Nano 目标文件的 SHA-256；
5. 编译命令和编译结果；
6. 编译后每个二进制 SHA-256；
7. 配置文件 SHA-256；
8. 备份目录和备份 SHA-256；
9. 是否部署到正式 `bin`；
10. 是否启动实体控制程序。

当前状态：`BACKUP_SNAPSHOT_MATCHED_SOURCE_COMMIT_MAPPING_PENDING`。
