# Linux CPU、内存、负载与 OOM 排查

> 来源类型：self_written（自写整理）
> 来源说明：依据 `top(1)`、`vmstat(8)`、`free(1)`、`pidstat(1)`、`/proc/meminfo`、`dmesg(1)` 的公开 man page 与内核文档语义整理
> 来源链接：https://man7.org/linux/man-pages/man1/top.1.html
> 适用系统：Linux 通用（openEuler / 麒麟 V10 均适用）
> 适用版本：procps-ng 3.3+、sysstat 12.x+
> 更新日期：2026-11-17
> 核实状态：指标语义为通用行为；systemd-oomd / earlyoom 等默认是否启用**未逐版本核实**

## 技术概念

- **load average 不是 CPU 使用率**：它是「可运行 + 不可中断（D 状态）」的进程数均值；磁盘 I/O 卡住也会把 load 顶高。
- **available ≠ free**：`free` 的 `available` 才是应用还能拿到的内存估计；`buff/cache` 可回收，不等于泄漏。
- **OOM killer**：内存耗尽时内核按评分杀进程，`dmesg`/`journalctl -k` 会留下 `Out of memory: Killed process`。
- **swap 与延迟**：swap 使用量高不必然是故障，但频繁换入换出会显著抬高延迟；`si/so` 持续非零是关键信号。
- **容器与 cgroup**：容器内看到的 CPU/内存可能是限额后的视图，排查要同时看宿主机 cgroup。

## 使用场景

- 服务响应变慢，怀疑 CPU 打满或内存不足。
- 进程被无故杀掉，需要确认是否 OOM。
- load 很高但 CPU 空闲（I/O 阻塞）。
- 需要判断扩容还是优化。

## 操作步骤

1. 先看整体：`uptime`（load）、`free -h`、`vmstat 1 5`。
2. 再定位进程：`top -b -n1 | head`、`pidstat -u -r -d 1 5`。
3. 区分 CPU 型、内存型、I/O 型：
   - CPU 型：`us+sy` 高、`id` 低；
   - I/O 型：`wa` 高、load 高但 `id` 不低；
   - 内存型：`available` 低、`si/so` 非零、OOM 记录。
4. 查 OOM：`journalctl -k | grep -i "out of memory"`，确认被杀进程与 cgroup。
5. 优化或扩容，并复测同一指标。

## 命令示例

```bash
uptime
free -h
vmstat 1 5

# 进程级 CPU/内存/IO，持续 5 次
pidstat -u -r -d 1 5

# 单进程线程级 CPU
pidstat -t -p <pid> 1 5

# OOM 记录（内核日志）
journalctl -k --since "1 hour ago" | grep -iE "out of memory|oom|killed process"

# 查看 cgroup 限额（cgroup v2 路径示例）
cat /sys/fs/cgroup/<slice>/memory.max
cat /sys/fs/cgroup/<slice>/cpu.max
```

## 预期输出及其含义（示意，非本机实测）

```text
$ free -h
              total   used   free  shared  buff/cache  available
Mem:           3.8Gi  3.1Gi  120Mi  12Mi       640Mi       420Mi
Swap:          2.0Gi  1.6Gi  400Mi
```

- `available` 仅 420Mi，`Swap used` 1.6Gi：内存压力明显，需先确认是否有异常进程或缓存策略问题。

```text
$ vmstat 1 5
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 1  8 1638400 122880 20480 655360  512  768   120   880  900 2200 12  6 40 42  0
```

- `b=8` 且 `wa=42`：大量进程处于不可中断等待，瓶颈在 I/O 而非 CPU；扩容 CPU 无效。

## 常见错误

| 现象 | 常见原因 | 判断 |
|---|---|---|
| load 高但 CPU idle 高 | 磁盘 I/O 阻塞、NFS 挂起 | `vmstat` 的 `wa`、`iostat -x` |
| 内存"用满"就判定泄漏 | 把 `buff/cache` 当作已用 | 看 `available` 与增长趋势 |
| 进程消失但无日志 | OOM killer、cgroup 限制、崩溃 | `journalctl -k`、`systemctl status` |
| 容器内内存正常，宿主告警 | 未看 cgroup/宿主视图 | 同时看两层 |

## 排查思路

先用 1 分钟粒度的三个视图（load / 内存 / swap+IO）定性，再用 `pidstat` 定量到进程，最后用 `journalctl -k` 找内核侧证据。结论必须落到「哪个进程、哪类资源、什么证据」，不能只写「负载高」。

## 安全注意事项

- 不要用 `kill -9` 作为常规手段；先尝试优雅停止并确认业务影响。
- 不要直接关闭 swap 或修改 `vm.swappiness` 作为"优化"，需评估业务与内核版本。
- 内存分析可能涉及业务数据，采样与日志导出要脱敏。
- 本文不提供任何压力测试脚本用于生产环境。

## 未核实与版本差异

- 麒麟 V10 较老内核（4.19 系列）与 openEuler 24.03（6.6 系列）在 cgroup v1/v2 默认、PSI 指标可得性上存在差异，本文未逐版本核实。
- 两发行版是否默认启用 `systemd-oomd`、是否预装 `sysstat`，需现场确认。
