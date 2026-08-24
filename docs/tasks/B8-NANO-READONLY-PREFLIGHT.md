# B8 Nano 只读预检准备

agent_number=3
task_name=B8-VM-SOFTWARE-ACCEPTANCE
delivery_id=agent-3/b8-vm-software-acceptance
platform=x86_64_vm
host=zzqVM
architecture=x86_64
jetson_nano=false
arm64_tested=false
nano_tested=false
entity_hardware_tested=false
entity_motion_tested=false
h1_status=H1_EVIDENCE_INCOMPLETE

H1：`H1_EVIDENCE_INCOMPLETE`

本文只是在 zzqVM 上准备的晚间人工只读检查清单。本任务未连接真实 Nano，也未执行下列命令。执行人员应先进入经授权的真实 Nano 终端，逐项只读采集，并把原始输出保存到新建证据目录；任何身份不符、权限不足或文件缺失都应停止检查并记录事实。

## 身份与 ARM64

```bash
hostname
hostnamectl
uname -a
uname -m
cat /etc/machine-id
```

期望人工确认主机身份明确，`uname -m` 为 `aarch64`。不满足时不得把结果归入 Nano 证据。

## JetPack 与 L4T

```bash
test -r /etc/nv_tegra_release && sed -n '1,20p' /etc/nv_tegra_release
dpkg-query -W 'nvidia-l4t-core' 'nvidia-jetpack' 2>&1
```

## Git 提交

```bash
pwd
git rev-parse HEAD
git branch --show-current
git status --short --branch
git log -1 --format=fuller
```

## 磁盘

```bash
df -hT
df -ih
du -sh .
```

## 进程与端口

```bash
ps -eo pid,ppid,user,lstart,stat,comm,args --sort=pid
ss -ltnup
```

## 共享内存

```bash
find /dev/shm -maxdepth 1 -mindepth 1 -printf '%M %u %g %s %TY-%Tm-%TdT%TH:%TM:%TS %f\n' | sort
```

## 串口节点与占用

```bash
find /dev/serial/by-id -maxdepth 1 -type l -printf '%f -> %l\n' 2>&1 | sort
ls -l /dev/serial/by-id 2>&1
fuser -v /dev/serial/by-id/* 2>&1
lsof /dev/serial/by-id/* 2>&1
```

这些命令仅查看节点和占用者，不打开设备做通信。

## 配置文件只读检查

```bash
find config -type f -printf '%M %u %g %s %TY-%Tm-%TdT%TH:%TM:%TS %p\n' | sort
find config -type f -exec sha256sum {} + | sort
```

## 二进制 SHA-256

```bash
find build -maxdepth 3 -type f -perm /111 -exec sha256sum {} + | sort
```

## 日志与备份目录规划

建议证据根目录命名为项目同级的 `evidence/b8-readonly-YYYYMMDD-HHMMSS`，其下规划 `identity/`、`software/`、`runtime/`、`serial-observation/`、`hashes/` 和 `logs/`。建议只读快照备份规划为同级 `backup-readonly-YYYYMMDD-HHMMSS/`。本清单不创建目录、不复制文件；实际落盘位置、容量和权限必须由现场负责人确认。

## 停止条件

身份不是预期设备、架构不是 `aarch64`、Git 提交不符、磁盘空间不足、发现未知进程或端口、共享内存来源不明、串口被未知进程占用、配置或二进制哈希不符时，立即停止并保存只读事实。不得将任何部分结果写成 Nano、ARM64、硬件或 H1 通过。
