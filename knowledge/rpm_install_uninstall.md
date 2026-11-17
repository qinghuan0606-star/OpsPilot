# RPM 安装与卸载：事务、路径冲突与残留

> 来源类型：self_written（自写整理）
> 来源说明：依据 `rpm(8)`、`dnf(8)`、`rpm2cpio(1)` 的公开 man page 与 RPM 事务语义整理
> 来源链接：https://rpm.org/docs/
> 适用系统：RPM 系 Linux；命令以 dnf 为包管理器
> 适用版本：rpm 4.14+、dnf 4.x
> 更新日期：2026-11-17
> 核实状态：事务与数据库语义已核实；`microdnf`/`yum` 兼容层在两发行版的默认可用性**未逐版本核实**

## 技术概念

- **RPM 数据库**：`/var/lib/rpm` 记录已安装包的 NEVRA（Name-Epoch-Version-Release-Arch）与文件清单、脚本、依赖。
- **事务（transaction）**：一次 dnf 操作可能包含多个包的安装/升级/卸载，要么整体成功，要么进入 `--cleanup`/回滚处理；中途断电可能留下未完成事务。
- **文件冲突**：两个包提供同一路径时事务报 `file /path conflicts between ...`，不会自动覆盖。
- **脚本片段**：`%pre/%post/%preun/%postun` 在安装/卸载阶段执行；脚本失败会让包处于半安装状态。
- **卸载不删配置**：默认删除包自带的配置文件（若被修改，会保留为 `.rpmsave`/`.rpmnew`），但**不会**删除运行期产生的数据目录。

## 使用场景

- 安装一个 RPM，但 dnf 报冲突、缺依赖或脚本报错。
- 卸载后服务仍存在（残留 unit 文件/用户/数据目录）。
- 事务中断后 `dnf` 持续报 "there are unfinished transactions"。
- 需要离线安装单包 `rpm -ivh` 与 `dnf install` 的选择。

## 操作步骤

1. 安装前先确认包来源与签名：`rpm -qp --qf`、`rpm -K`。
2. 优先用 `dnf install` 解析依赖，不要直接 `rpm -ivh` 跳过依赖。
3. 出现冲突先看冲突路径归属：`rpm -qf <路径>`。
4. 卸载前确认没有其他包依赖它：`rpm -q --whatrequires`。
5. 卸载后检查残留：unit、用户、数据目录、配置备份。
6. 事务异常先 `dnf history` 定位，再按官方方式修复，不手工删 rpmdb。

## 命令示例

```bash
# 安装（推荐，自动解析依赖与签名校验）
dnf install -y <包名>
dnf install -y ./<本地文件>.rpm

# 离线单包安装（仅在依赖已满足时使用）
rpm -ivh <本地文件>.rpm

# 校验包来源与签名
rpm -K <本地文件>.rpm
rpm -qp --qf '%{NAME} %{VERSION}-%{RELEASE} %{ARCH} %{SIGPGP:pgpsig}\n' <本地文件>.rpm

# 查文件归属与冲突归属
rpm -qf /usr/bin/<命令>
rpm -ql <包名>

# 卸载
dnf remove -y <包名>
rpm -e <包名>            # 仅在不涉及依赖时使用

# 历史与未完成事务
dnf history
dnf history info <ID>
dnf history undo <ID>    # 仅在支持且可回退的事务上使用
```

## 预期输出及其含义（示意，非本机实测）

```text
$ rpm -q --whatrequires nginx-mod-http-geoip
nginx-mod-http-geoip-1.20.1-16.oe2403.x86_64
```

- 输出为空表示没有其他已安装包显式依赖它；但运行时 `dlopen` 的隐式依赖不会出现在这里，仍需看日志。

```text
$ dnf remove nginx-mod-http-geoip
Error: Problem: The operation would result in removing the following protected packages: nginx
```

- 说明该包被事务视为受保护依赖链的一部分，应改用升级子包而不是强行卸载。

## 常见错误

| 现象 | 常见原因 | 处理方向 |
|---|---|---|
| `file ... conflicts between` | 两个包提供同一路径 | `rpm -qf` 定位归属，评估替换或排除 |
| `Failed dependencies` | 缺库/缺包/版本区间不满足 | 用 dnf 解析；离线环境补齐仓库 |
| `scriptlet failed, exit status 1` | `%pre/%post` 执行失败（目录不存在、用户不存在、SELinux 拒绝） | 查 `dnf` 输出与 `/var/log/dnf.log`，修复条件后重试 |
| `rpmdb: BDB0113` / 数据库损坏 | 断电、并发写、磁盘满 | 备份 `/var/lib/rpm` 后用官方 `rpm --rebuilddb`，不要直接删除 |
| 卸载后服务仍能启动 | unit 文件来自其他包或手工创建；`/etc` 配置保留 | `rpm -qf`、`systemctl cat` 确认来源 |

## 排查思路

按「包是否装成功 → 文件是否落盘 → 脚本是否成功 → 依赖是否满足 → 服务是否重启」逐层确认。判断安装是否成功不要只看命令退出码，用 `rpm -q <包名>` 与 `rpm -V <包名>` 复核。

## 安全注意事项

- 不要用 `rpm --nodeps --force` 绕过依赖；这会制造不可见的不一致，后续升级会失败。
- 不要手工删除 `/var/lib/rpm` 下的数据库文件；损坏时应先备份再重建。
- 安装第三方 RPM 前核对签名与来源，禁止直接执行来源不明的包脚本。
- 卸载前确认业务依赖与回退包可用。

## 未核实与版本差异

- openEuler 与麒麟 V10 的默认仓库配置、是否默认启用 GPG 校验、`microdnf` 是否可用，未逐版本核实。
- 两发行版对 `%post` 脚本失败的处理严格程度可能不同，需现场验证。
