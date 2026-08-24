# H1 新实体只读记录目录

状态：`PREPARED_NOT_EXECUTED`

这是今晚补采使用的新目录模板。当前目录没有实体新采样、没有设备访问、没有 PASS 结论。

执行后把同一只读窗口产生的原始文件放入本目录，并填写 `record.template.json`。完成后再将模板复制为实际 `record.json`，不得修改旧目录 `entity-raw/pose-readout-19700101T023629Z-retry1/`。

建议文件：

```text
record.template.json
sha256-manifest.template.json
commands.log
samples.jsonl
report.json
README.md
```

现阶段只保留模板和清单，不填写 `PASS`、设备状态或不存在的实体数据。
