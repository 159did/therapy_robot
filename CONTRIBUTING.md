# 多人协作说明

## 基本规则

- `main` 只接受 Pull Request，不直接 push。
- 分支命名：`feature/<任务>`、`fix/<任务>`、`docs/<任务>`。
- 每个 PR 必须说明修改范围、测试命令、未解决项和实体安全影响。
- 纯软件任务不得访问串口、D405、共享内存或生成电机目标。
- 实体窗口必须由项目负责人单独批准；代码合并不等于实体授权。

## 合并门禁

```text
Python 语法检查
B4/B5 离线测试
CMake/CTest
git diff --check
敏感信息扫描
至少一名审核人批准
```

## 推荐流程

```text
git switch -c feature/<task>
开发 -> 本地测试 -> 提交 -> Pull Request -> 审核 -> 合并 main
```
