# GitHub 私有仓库上传准备

基线：`64bc8b0bb5da41d12fb99fcbb3e2d5c915407664`

## 结论

- 允许范围：仅受邀成员可见的 GitHub Private 仓库。
- 推送范围：只推 `main`；不推所有本地分支、标签或镜像。
- 当前禁止：Public 仓库、公开 fork、公开发布包。
- 本次只做仓库检查和协作准备，没有向 GitHub 上传。

## 检查结果

- `main` 在检查开始时干净，没有配置远程地址。
- 当前 `main` 有 74 个提交、348 个跟踪文件；没有超过 50 MiB 的单文件。
- 根目录压缩归档和 `backups/` 均未被 Git 跟踪。
- 当前文件和 `main` 历史未发现 SSH 私钥头、GitHub Token 或 AWS Access Key 模式。
- 提交作者邮箱为本地占位地址 `ptr-local@localhost`，不会关联个人 GitHub 贡献；不影响推送。
- 已知含真实硬件映射、实体标定、背部/D405 样本及论文结果目录中的副本，
  因此只能私有上传。

## 软件验证

- B4 离线测试：31 项通过。
- B6 离线测试：40 项通过。
- 仓库顶层离线测试：74 项通过。
- GitHub Actions 声明的 C++ 目标全部构建成功。
- CTest：17/17 通过。
- Python 编译检查和 `git diff --check` 通过。
- 编译过程只有既有测试源码的未使用变量警告，没有编译错误。

## 上传前剩余的人为步骤

1. 确定 GitHub 用户名、私有仓库名称和受邀成员。
2. 在 GitHub 创建空的 Private 仓库。
3. 确认 GitHub SSH 公钥认证可用。
4. 按 `PUBLISHING.md` 添加 `origin` 并只推 `main`。
5. 推送后启用 `main` 分支保护和 Actions 门禁。

创建仓库或推送不会授权 Nano 部署、串口访问、D405 访问或电机控制。
