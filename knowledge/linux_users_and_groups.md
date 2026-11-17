# Linux 用户、用户组与登录排查

> 来源类型：self_written（自写整理）
> 来源说明：依据 `useradd(8)`、`usermod(8)`、`groupadd(8)`、`passwd(1)`、`id(1)`、`getent(1)` 的公开 man page 语义整理，不复制任何厂商文档
> 来源链接：https://man7.org/linux/man-pages/man8/useradd.8.html
> 适用系统：Linux 通用（openEuler / 麒麟 V10 均适用）
> 适用版本：shadow-utils 4.x 及以上
> 更新日期：2026-11-17
> 核实状态：命令与参数为通用行为；两发行版默认 uid/gid 起始值、密码策略默认值**未逐版本核实**，以现场配置为准

## 技术概念

Linux 的权限主体是「用户（user）+ 用户组（group）」，不是单一账号密码：

- **UID/GID**：内核用数字识别身份，`0` 为 root；`/etc/passwd`、`/etc/group` 是名称到数字的映射。
- **主组与附加组**：用户有且只有一个主组（决定新建文件的默认属组），可加入多个附加组（获得额外资源访问权）。
- **系统用户**：为服务运行创建的低权限账号（通常 uid < 1000，`/sbin/nologin` 作为 shell），例如 `nginx`、`sshd`。
- **影子文件**：`/etc/shadow` 保存密码哈希与过期策略，权限应为 `0000` 或 `0400`，仅 root 可读。

## 使用场景

- 新建运维账号并授予最小权限，而不是共用 root。
- 服务启动报 `Permission denied`、`cannot open /var/log/...`，需要判断服务以哪个用户运行。
- 排查「同一台机器，A 能读、B 不能读」的权限类故障。
- 账号被锁定、密码过期、登录被 PAM 拒绝。

## 操作步骤

1. 先确认目标账号当前状态，不要直接改。
2. 创建用户/组，显式指定 shell 与家目录。
3. 通过附加组授权，不直接改文件属主。
4. 修改后重新登录验证（组变更不会自动进入已存在的会话）。
5. 记录变更，避免与配置管理系统冲突。

## 命令示例

```bash
# 查看当前身份与所属组
id
id nginx

# 名称服务解析（比直接 cat /etc/passwd 更可靠，兼容 LDAP/SSSD）
getent passwd nginx
getent group wheel

# 创建系统组与系统用户（服务账号，不给登录 shell）
groupadd -r appops
useradd -r -g appops -s /sbin/nologin -d /var/lib/appops appops

# 给运维账号追加附加组（-a 必须保留，否则会覆盖原有附加组）
usermod -aG wheel opsuser

# 查看密码与过期策略
chage -l opsuser

# 锁定 / 解锁账号
usermod -L opsuser
usermod -U opsuser
```

## 预期输出及其含义（示意，非本机实测）

```text
$ id nginx
uid=996(nginx) gid=994(nginx) groups=994(nginx)

$ getent group wheel
wheel:x:10:opsuser
```

- `uid=996` 处于系统账号区间，说明它是服务账号，不应期待可登录 shell。
- `groups=` 里没有目标组，说明附加组未生效：需要 `usermod -aG` 后重新登录。
- `getent` 无输出而 `/etc/passwd` 有记录，说明名称服务缓存或 nsswitch 配置有问题，不要只改本地文件。

## 常见错误

| 现象 | 常见原因 | 判断方式 |
|---|---|---|
| `usermod: user 'x' is currently used by process` | 该用户仍有登录会话或服务进程 | `who`、`ps -u x` 确认后再操作 |
| 追加组后权限仍不足 | 用了 `usermod -G` 覆盖了原附加组；或会话未重新登录 | `id` 查看当前会话的组列表 |
| 服务报无法写目录 | 目录属主/属组与服务运行用户不一致，或父目录缺少 `x` 权限 | `namei -l /path` 逐级查看 |
| `su: Authentication failure` 但密码正确 | PAM、`/etc/shadow` 权限、SELinux 上下文 | `journalctl -u sshd`、`/var/log/secure` |

## 排查思路

1. 先确认「进程以谁的身份运行」：`ps -o user,group,cmd -p <pid>`。
2. 再确认「目标资源要求谁」：`namei -l` 看每一级目录权限，`ls -lZ` 看 SELinux 标签。
3. 最后确认「名称服务是否一致」：`getent` 与本地文件对照。
4. 不要用 `chmod 777` 绕过：先判断是属组、ACL 还是 SELinux 的问题。

## 安全注意事项

- 不要给服务账号分配登录 shell；不要用 root 直接跑业务进程。
- `/etc/shadow` 权限被放宽是高风险配置，应恢复为仅 root 可读。
- 批量改用户前先备份 `/etc/passwd`、`/etc/group`、`/etc/shadow`，并保留变更记录。
- 本文不包含任何「绕过认证」的操作；账号异常应走审计与工单流程。

## 未核实与版本差异

- openEuler 与麒麟 V10 的默认 `UID_MIN/UID_MAX`、密码过期默认策略可能不同，本文未给出具体数值。
- `wheel` 组是否默认存在、sudoers 是否默认包含 `%wheel`，需在目标机上 `getent group wheel`、`grep wheel /etc/sudoers` 现场确认。
