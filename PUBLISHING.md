# 私有 GitHub 上传说明

当前版本可以上传到私有仓库供受邀成员协作；上传不等于部署 Nano 或授权实体设备。

## 上传前确认

1. 创建 **Private** GitHub repository，初始仓库不要自动添加 README、license 或 `.gitignore`。
2. 只邀请项目成员；启用两步验证和 `main` 分支保护。
3. 添加远程后推送 `main`，不要把 SSH 私钥或 GitHub Token 写入仓库。
4. 在 GitHub 设置中要求 Pull Request、至少一人审核和 Actions 通过后才能合并。

## 公开发布禁止项

当前仓库包含真实设备相关配置、实体 K0/offset 观测和相机/背部样本。它们可在项目成员范围的私有仓库中保留，但不得直接公开。公开前必须用 example/synthetic 数据替换，并从 Git 历史中清理敏感版本。

运行以下只读扫描可得到当前清单：

```bash
python3 scripts/repository_safety_scan.py --root .
```
