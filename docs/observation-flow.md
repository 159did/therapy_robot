# 无接触观察流程（本地编写版）

`scripts/observation_flow.py` 把已经存在的路线和视觉离线输出串成一条完整的观察流程，供 Nano 同步前编译和验证：

```text
BOOT
 -> SAFE_HIGH
 -> SIDE_ROTATED
 -> ARM_EXTENDED
 -> CAMERA_CAPTURED
 -> ACUPOINTS_READ
 -> HOVER_TARGET
 -> HOLD_NO_CONTACT
 -> RETRACTED
 -> RETURN_HIGH
 -> COMPLETE
```

这里的 `CAMERA_CAPTURED` 是“读取已生成的离线视觉结果”，不是打开 D405 拍照；`HOVER_TARGET` 是候选目标点上方的位置记录，不是电机目标。`COMPLETE` 只表示离线编排完成，不代表实体执行许可。

运行左侧流程：

```bash
python3 scripts/observation_flow.py \
  --route docs/progress/evidence/B5/DEMO/route-left-from-b5-m1-m2.json \
  --vision docs/progress/evidence/B5/DEMO/vision-from-b5-vision.json \
  --side left \
  --output /tmp/observation-left.json
```

输出报告会给出路线和视觉输入 SHA-256、选中穴位、候选悬停坐标、有效穴位数量，以及每个状态的明细。所有实体权限字段固定为 `false`。本文件、脚本和测试已同步到 Nano 的 `/home/zzq/PTR/therapy_robot`，当前保持未提交状态；同步前原文件已保存在 `/home/zzq/PTR/backups/observation-flow-20260823T102359Z`。Nano 上只执行了离线编译、单元测试和 fixture 编排，没有启动服务、打开相机或控制实体硬件。
