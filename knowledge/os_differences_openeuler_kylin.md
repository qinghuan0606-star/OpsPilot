# openEuler 与麒麟 V10 系统管理差异核对表（公开资料层面）

> 来源类型：public_summary（公开资料摘要）
> 来源说明：仅依据 openEuler 社区与麒麟软件公开发布的版本信息、通用 Linux/RPM/systemd 文档整理；**未获取、也未声称任何厂商内部文档**
> 来源链接：https://docs.openeuler.org/ 、https://www.kylinos.cn/
> 适用系统：openEuler 24.03 LTS（含 SP1）、Kylin V10 SP3
> 适用版本：openEuler 24.03 LTS-SP1（内核 6.6 系列）、Kylin V10 SP3（内核 4.19 系列）
> 更新日期：2026-11-17
> 核实状态：**多数差异未在真实机器上逐条验证**。本表把「已验证的通用行为」「公开资料可确认的发行版信息」「尚未核实的差异」分开标注，禁止把通用知识当作某发行版官方结论

## 技术概念

两个发行版都是 Linux + RPM + systemd 技术底座，通用层（权限、进程、RPM 数据库、systemd 单元语义、journald）基本一致；差异集中在**版本年代、默认组件、仓库与包命名、安全默认值、内核能力**。因此判断差异的正确姿势是：

1. 先确认「这是 Linux 通用行为」还是「发行版默认配置」；
2. 发行版默认配置必须现场取证（`/etc/os-release`、`rpm -q`、`systemctl show`）；
3. 未取证前，不把 openEuler 的命令/配置直接套到麒麟 V10。

## 使用场景

- 在 openEuler 上验证过的排查步骤，要迁移到麒麟 V10。
- 同一服务在两地表现不同，需要先排除版本与默认配置差异。
- 编写跨发行版的运维脚本/文档，需要标注适用边界。
- 回答"这两个系统有什么区别"时，避免编造具体差异。

## 分类一：Linux 通用（两发行版均适用，已核实语义）

以下属于 Linux/RPM/systemd 通用语义，不因发行版而改变（默认值可能不同）：

- 文件权限位、`namei -l`、`getfacl` 的语义。
- `rpm -q/-ql/-qf/-V`、NEVRA 结构、`/var/lib/rpm` 数据库职责。
- systemd unit 的 `[Unit]/[Service]/[Install]` 段与 `After/Wants/Requires` 语义。
- `journalctl -u <unit>`、`systemctl status`、`systemctl cat`。
- `ip addr`/`ip route`/`ss -lntp` 的基本用法。
- `df -h`/`df -i`/`du -x` 的统计口径。

**注意**：语义一致 ≠ 默认值一致。例如默认 umask、默认文件系统、默认防火墙 zone 都可能不同。

## 分类二：公开资料可确认的发行版信息（仍需现场复核具体小版本）

| 维度 | openEuler 24.03 LTS-SP1（公开信息） | Kylin V10 SP3（公开信息） | 取证方式 |
|---|---|---|---|
| 版本标识 | `/etc/openEuler-release`、`/etc/os-release` | `/etc/kylin-release`、`/etc/os-release` | `cat /etc/os-release` |
| 内核系列 | 6.6 系列（本文档写作时的公开基线） | 4.19 系列（SP3 常见基线） | `uname -r` |
| 包管理 | dnf/rpm，dnf 4.x | dnf/rpm（版本可能较旧），兼容 yum 命令习惯 | `dnf --version` |
| 服务管理 | systemd | systemd | `systemctl --version` |
| 默认安全组件 | 以现场为准（SELinux/firewalld 配置可能随镜像不同） | 常见 firewalld + SELinux 启用 | `getenforce`、`systemctl status firewalld` |
| 包命名 | 常见 `.oe2403` 后缀 | 常见 `.ky10` 后缀 | `rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' <包>` |

> 表中"常见/可能"均为公开资料层面的概括，**不是逐台机器的保证**；任何结论都要以现场命令输出为准。

## 分类三：需要重点核对的差异点（本文明确标注为「未逐版本核实」）

1. **内核与 cgroup 版本**：4.19 与 6.6 在 cgroup v1/v2 默认、PSI、eBPF 能力上差异明显，影响容器与资源排查手段。未在麒麟 V10 SP3 实机核对。
2. **容器运行时默认**：docker-ce/containerd/podman 的默认组合与存储驱动（overlay2 等）不同镜像可能不同。未核实。
3. **默认文件系统与 LVM 布局**：影响扩容命令（`xfs_growfs` vs `resize2fs`）。未核实。
4. **默认仓库与模块化支持**：仓库地址、是否启用 modules、可用软件版本区间不同。未核实具体 URL/stream。
5. **安全默认值**：SELinux 策略、firewalld 默认 zone、密码策略（`/etc/security/pwquality.conf`）可能不同。未核实。
6. **systemd 可用指令**：老版本 systemd 可能不支持较新的 `ProtectProc=`、`RestartMode=` 等，需 `man` 现场确认。未核实具体版本号。
7. **审计与日志默认**：`/var/log/messages` 是否存在、journald 是否持久化（`/var/log/journal`）不同。未核实。

## 操作步骤（跨发行版迁移排查步骤时）

1. 采集发行版基线：`cat /etc/os-release`、`uname -r`、`dnf --version`、`systemctl --version`。
2. 采集包版本：`rpm -q <关键包>`，记录完整 NEVRA。
3. 采集默认配置：`getenforce`、`firewall-cmd --state`、`findmnt /`、`cat /etc/fstab`。
4. 对每一步命令，先判断它属于「通用语义」还是「依赖默认值」；后者必须在目标机重新取证。
5. 在文档/脚本里写清适用系统与版本，未知项标注 TODO，而不是猜测。

## 命令示例

```bash
# 发行版与内核基线（两系统都先跑这一组）
cat /etc/os-release
uname -r
getconf LONG_BIT

# 包管理器与服务管理器版本
dnf --version | head -2
systemctl --version | head -2

# 关键包 NEVRA（用于区分 .oe2403 / .ky10）
rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' systemd kernel

# 安全与文件系统默认
getenforce 2>/dev/null || echo "selinux tool missing"
firewall-cmd --state 2>/dev/null || echo "firewalld not running/installed"
findmnt -no FSTYPE /
```

## 预期输出及其含义（示意，非本机实测）

```text
$ cat /etc/os-release
NAME="openEuler"
VERSION="24.03 (LTS-SP1)"
ID="openEuler"

$ uname -r
6.6.0-28.0.0.31.oe2403.x86_64
```

- `.oe2403` 出现在内核 release 中，是 openEuler 构建标识；换到麒麟应看到 `.ky10` 标识。这只是识别线索，不代表命令行为完全一致。

```text
$ rpm -q --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel
kernel-4.19.90-52.22.v2207.ky10.x86_64
```

- 记录完整 NEVRA 才能在报告里说清"在哪个版本上验证过"。

## 常见错误

| 错误做法 | 后果 | 正确做法 |
|---|---|---|
| 把 openEuler 的仓库地址写进麒麟机器的 repo | 元数据/签名校验失败或装错包 | 用目标机自带仓库，先 `repolist` |
| 直接把 `xfs_growfs` 用在 ext4 | 扩容失败甚至报错 | `df -T` 确认文件系统 |
| 认为 systemd 指令两边完全一致 | 老版本 unit 指令不识别，服务不起 | `man systemd.service` 现场核对 |
| 把通用 Linux 文档标成"麒麟官方文档" | 来源失真 | 标 `self_written`/`public_summary` + 适用版本 |
| 用"应该一样"解释故障 | 掩盖真实版本差异 | 采集 NEVRA 与默认配置做证据 |

## 排查思路

先取基线（发行版、内核、包版本、安全状态、文件系统），再做对照；差异结论必须附命令输出。没有输出支撑的"差异"只能写成待核实项，不能写成事实。

## 安全注意事项

- 不要把任一发行版的"关闭 SELinux/防火墙"步骤当作通用修复。
- 跨发行版复制仓库配置会引入供应链风险；包来源必须可验证。
- 本文不提供任何厂商内部资料或未公开补丁信息。

## 未核实清单（明确保留）

- 麒麟 V10 SP3 默认 systemd 具体版本与可用指令集。
- 两发行版默认文件系统、LVM 布局、inode 密度。
- 两发行版默认 firewalld zone、SELinux 策略、密码策略参数。
- 两发行版默认仓库 URL、模块流、是否预装容器运行时。
- 以上均需在目标机执行本文命令后补录；在补录前，OpsPilot 的知识检索只会给出"需现场核实"的提示，不给出确定性差异结论。
