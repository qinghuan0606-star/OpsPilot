# Linux 文件权限、ACL 与 umask

> 来源类型：self_written（自写整理）
> 来源说明：依据 `chmod(1)`、`chown(1)`、`umask(1)`、`acl(5)`、`setfacl(1)`、`chattr(1)` 的公开 man page 语义整理
> 来源链接：https://man7.org/linux/man-pages/man1/chmod.1.html
> 适用系统：Linux 通用（openEuler / 麒麟 V10 均适用）
> 适用版本：coreutils 8.x 及以上；ACL 需文件系统挂载支持 acl
> 更新日期：2026-11-17
> 核实状态：权限位语义为通用行为；XFS/ext4 默认 ACL 挂载参数**未逐版本核实**

## 技术概念

- **三类主体 × 三种权限**：属主（u）、属组（g）、其他（o）分别有读（r=4）、写（w=2）、执行（x=1）。
- **目录的 x 位是「进入」**：目录没有 `x` 时，里面的文件即使 `r` 可读也打不开；目录没有 `w` 时不能新建/删除条目。
- **粘滞位（t）**：`/tmp` 常见 `1777`，任何用户可写，但只能删除自己的文件。
- **umask 是「屏蔽位」不是权限值**：`umask 022` 表示新建文件默认 `644`、目录 `755`。
- **ACL**：在不改属主的情况下，为特定用户/组授予细粒度权限，`getfacl` 查看、`setfacl` 设置。
- **扩展属性**：`chattr +i` 置为不可修改（连 root 也需先去掉），常用于保护关键配置。

## 使用场景

- 服务以低权限账号运行，需要读取配置/写日志目录，但不想把整个目录改成 777。
- 多人协作目录需要「同组可写、其他人只读」。
- 排查"文件明明有 r 权限却打不开"（父目录缺 x）。
- 需要临时阻止误删关键文件。

## 操作步骤

1. 用 `namei -l` 从根到目标逐级看权限，判断卡在哪一层。
2. 用 `ls -l` / `getfacl` 区分普通权限位与 ACL。
3. 优先调整属组 + `g+w`（或 ACL），不调整 `o`。
4. 变更后以目标用户实际验证一次读取/写入。

## 命令示例

```bash
# 逐级查看路径权限
namei -l /var/lib/appops/data

# 查 ACL
getfacl -p /var/log/appops

# 给服务组读+执行目录、读文件（不放开 other）
chgrp -R appops /var/lib/appops
chmod -R g+rX /var/lib/appops

# 用 ACL 只给特定用户写权限
setfacl -m u:opsuser:rwx /var/log/appops
setfacl -d -m g:appops:rwx /var/log/appops   # 目录默认 ACL，影响新建文件

# 设置 umask（当前会话）
umask 027

# 保护关键配置（需 root；去掉用 -i）
chattr +i /etc/ssh/sshd_config
lsattr /etc/ssh/sshd_config
```

## 预期输出及其含义（示意，非本机实测）

```text
$ namei -l /var/lib/appops/data
f: /var/lib/appops/data
drwxr-xr-x root root /
drwxr-xr-x root root var
drwxr-xr-x root root lib
drwxr-xr-x root root appops
drwxrwx--- appops appops data
```

- 前四级都是 `x` 可进入，最后一级属组 `appops` 有 `rwx`：服务账号在 `appops` 组内即可读写。
- 若某一级显示 `drwxr-x--- root root` 而服务账号不在 `root` 组，则服务会在 `open()` 处直接 `EACCES`，此时改最深一层没用。

```text
$ getfacl -p /var/log/appops
# file: /var/log/appops
# owner: root
# group: appops
user::rwx
user:opsuser:rwx
group::r-x
mask::rwx
other::---
```

- 出现 `user:opsuser:rwx` 说明走的是 ACL，不是普通 `o` 权限；`mask` 会限制 ACL 条目的实际上限。

## 常见错误

| 现象 | 常见原因 |
|---|---|
| `Permission denied` 但文件是 644 | 父目录缺 `x`；或 ACL mask 把权限裁掉 |
| 新建文件权限不是预期 | 进程继承了不同的 umask（systemd 服务有 `UMask=` 配置） |
| `setfacl: Operation not supported` | 文件系统未启用 acl（如某些 tmpfs/NFS 挂载参数） |
| 改了权限但服务仍失败 | SELinux 标签不对，或服务有 `ProtectSystem=`/`ReadOnlyPaths=` 限制 |

## 排查思路

1. `namei -l` 逐级定位；2. `getfacl` 看 ACL 与 mask；3. `ls -Z` 看 SELinux；4. `systemctl cat` 看 `User=`、`UMask=`、`Protect*=`；5. 用 `sudo -u <服务用户> test -r <文件>` 复现。

## 安全注意事项

- 禁止用 `chmod -R 777` 解决权限问题；它会同时放开写入与执行，是常见提权入口。
- 不要把服务账号加入 `root`、`wheel` 等高权组来"省事"。
- `chattr +i` 会影响配置管理与自动化变更，使用前要记录并设计回退。
- 本文不提供任何提权或绕过审计的做法。

## 未核实与版本差异

- openEuler 与麒麟 V10 默认挂载参数是否带 `acl`，需现场 `mount | grep <设备>` 确认。
- 两发行版默认 systemd 服务的 `UMask=` 值与 SELinux 默认策略**未逐版本核实**。
