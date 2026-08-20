# 私有 GitHub 上传说明

当前版本可以上传到私有仓库供受邀成员协作；上传不等于部署 Nano 或授权实体设备。
由于 Git 历史包含真实标定、设备配置和背部/D405 样本，本仓库当前不得设为 Public。

## 上传前确认

1. 在 GitHub 创建 **Private** repository；不要自动添加 README、license 或 `.gitignore`。
2. 在本仓库运行 `python3 scripts/github_private_preflight.py --root .`，必须得到
   `ready_for_private_push=true`。
3. 只邀请课题成员；GitHub 账户启用两步验证。
4. 首次推送只推 `main`。本机保留了大量阶段分支，不执行 `git push --all`，也不推本地标签。
5. 首次推送完成后，为 `main` 启用分支保护：要求 Pull Request 和
   `software-validation / offline` 通过。只有一名开发者时可暂不要求他人审核。

## 首次上传命令

先在 GitHub 网页创建空的私有仓库，再在 zzq 上运行：

```bash
cd /home/zzq/PTR/therapy_robot
python3 scripts/github_private_preflight.py --root .
git remote add origin git@github.com:<GitHub用户名>/<仓库名>.git
git remote -v
git push -u origin main
```

若 `origin` 已存在，先检查地址，不要盲目覆盖：

```bash
git remote get-url origin
```

明确禁止：

```bash
git push --all
git push --mirror
git push --tags
```

不要把 GitHub Token 写进远程 URL、脚本、`.env` 或命令记录。优先使用已配置的 SSH 公钥认证。

## 上传内容说明

首次上传会包含 `main` 的完整提交历史，而不是只有当前文件快照。当前扫描未发现
SSH 私钥、GitHub Token 或 AWS Access Key，但确认含有以下受限内容：

- `config/jetson-hardware.env` 的实体设备映射和运行参数；
- `calibration/` 中的实体 K0、轴 offset 和相机观测；
- `back/back.png` 与 `data/d405_samples/` 中的背部/D405 样本；
- 文档和证据中的本机路径。

这些内容只允许受邀课题成员访问。若以后要公开，必须另做脱敏发布历史，不能直接把该仓库切换为 Public。

## 公开发布禁止项

当前仓库包含真实设备相关配置、实体 K0/offset 观测和相机/背部样本。它们可在项目成员范围的私有仓库中保留，但不得直接公开。公开前必须用 example/synthetic 数据替换，并从 Git 历史中清理敏感版本。

运行以下只读扫描可得到当前清单：

```bash
python3 scripts/repository_safety_scan.py --root .
```
