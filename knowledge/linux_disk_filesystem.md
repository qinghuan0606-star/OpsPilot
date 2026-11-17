# 磁盘、文件系统与 inode 排查

> 来源类型：self_written（自写整理）
> 来源说明：依据 `df(1)`、`du(1)`、`find(1)`、`lsblk(8)`、`lvs(8)`、`xfs_repair(8)` 的公开 man page 语义整理
> 来源链接：https://man7.org/linux/man-pages/man1/df.1.html
> 适用系统：Linux 通用（openEuler / 麒麟 V10 均适用）
> 适用版本：coreutils 8.x+、util-linux 2.37+、LVM2 2.03+
> 更新日期：2026-11-17
> 核实状态：通用命令与概念已核实；两发行版默认文件系统**未逐版本核实**

## 技术概念

- **空间与 inode 是两套资源**：`df -h` 看块空间，`df -i` 看 inode；小文件过多会先耗尽 inode，此时仍有剩余空间却报 `No space left on device`。
- **删除文件后空间未释放**：进程持有已删除文件的句柄时，空间计入 `df` 但 `du` 看不到；需重启/优雅重启该进程或清空其句柄。
- **保留块**：ext4 默认给 root 保留 5% 空间，`df` 的 `Avail` 会小于 `Free`。
- **挂载覆盖**：目录已有数据时挂载新文件系统，原数据被"盖住"但未删除，排查时会误判空间去向。
- **LVM**：PV → VG → LV，扩容通常分「扩 LV → 扩文件系统」两步，只做一步不生效。

## 使用场景

- 服务写入失败，日志报 `No space left on device`。
- 磁盘使用率告警，但 `du` 加总远小于 `df`。
- inode 耗尽导致无法创建新文件。
- 需要扩容 `/data` 或 `/var`。

## 操作步骤

1. `df -h` 与 `df -i` 同时看，区分空间型与 inode 型。
2. `lsblk -f` 确认设备、文件系统类型与挂载点。
3. `du -x -h --max-depth=1 <挂载点>` 按目录定位（`-x` 不跨文件系统）。
4. 若 `df` ≫ `du`，检查被删除但仍被占用的文件。
5. 清理前先确认文件归属与保留策略；扩容时按文件系统类型选择工具。

## 命令示例

```bash
# 空间 + inode
df -hT
df -i

# 块设备与文件系统
lsblk -f

# 目录级占用（不跨文件系统）
du -x -h --max-depth=1 /var | sort -h

# 找大文件（示例阈值 200M）
find /var -xdev -type f -size +200M -printf '%s %p\n' 2>/dev/null | sort -n | tail -20

# 被删除但仍被进程占用的文件
lsof +L1 2>/dev/null | head -20

# LVM 扩展示例（务必先确认 VG 有可分配空间）
vgs
lvs
lvextend -L +10G /dev/<vg>/<lv>
xfs_growfs /data          # XFS
resize2fs /dev/<vg>/<lv>  # ext4
```

## 预期输出及其含义（示意，非本机实测）

```text
$ df -hT /data
Filesystem     Type  Size  Used Avail Use% Mounted on
/dev/mapper/vg-lv_data xfs 100G 90G 10G 90% /data
```

- `Avail` 才是应用实际可写的余量；`Use%` 高但 `Avail` 仍有空间时，先确认是否触及 inode 或配额。

```text
$ df -i /data
Filesystem      Inodes  IUsed   IFree IUse% Mounted on
/dev/mapper/vg-lv_data 6553600 6553000 600 100% /data
```

- `IUse% 100%` 且空间充足：应清理小文件/缓存目录，扩 inode 通常需要重建文件系统，风险高。

```text
$ lsof +L1
COMMAND PID USER FD TYPE DEVICE SIZE/OFF NLINK NODE NAME
nginx   812 root 5w REG  253,0 12G 0 1234567 /var/log/nginx/access.log (deleted)
```

- `NLINK 0` 且 `(deleted)`：文件已删除但被进程持有，空间未归还。

## 常见错误

| 现象 | 常见原因 | 处理方向 |
|---|---|---|
| `No space left on device` 但 `df` 有空间 | inode 耗尽、目录配额、保留块 | `df -i`、`repquota` |
| 删除大日志后空间没变 | 进程仍持有句柄 | `lsof +L1`，reload/restart 服务 |
| 扩容后 `df` 没变化 | 只扩了 LV，没扩文件系统 | 按类型执行 `xfs_growfs`/`resize2fs` |
| 目录看似空却占满 | 有隐藏挂载点覆盖；或大量已删除文件 | `findmnt`、`lsof +L1` |
| `du` 统计比 `df` 小很多 | 跨挂载点重复统计、句柄占用、稀疏文件 | 用 `-x`，并核对挂载 |

## 排查思路

先分型（空间 / inode / 配额 / 句柄）→ 再定位目录 → 再确认文件归属与可清理性 → 最后才考虑扩容。扩容是"增加供给"，不能替代"确认到底是什么在增长"；否则扩完很快再次告警。

## 安全注意事项

- 不要对 `/`、`/var` 执行无条件递归删除；先按属主、修改时间、是否被进程打开筛选。
- `xfs_repair`、`resize2fs` 等操作有数据风险，必须在维护窗口并先备份。
- 清理日志前确认 logrotate 策略与审计留存要求；不要删除审计日志。
- 本文不提供任何"清空根目录"类破坏性命令。

## 未核实与版本差异

- openEuler 24.03 与麒麟 V10 默认根文件系统（XFS/ext4）未逐版本核实，扩缩容命令必须按 `df -T` 实际类型选择。
- 两发行版默认 inode 密度与 LVM 默认布局不同，未核实。
