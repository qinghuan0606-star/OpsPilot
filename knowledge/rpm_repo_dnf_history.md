# RPM 仓库、模块化软件包与 dnf 历史

> 来源类型：self_written（自写整理）
> 来源说明：依据 `dnf(8)`、`dnf.conf(5)`、`repoquery(1)` 的公开 man page 与 Fedora/openEuler 公共仓库语义整理
> 来源链接：https://dnf.readthedocs.io/
> 适用系统：RPM 系 Linux（openEuler 与麒麟 V10 均适用 dnf 基本语义，仓库地址不同）
> 适用版本：dnf 4.x；`dnf module` 需模块化仓库支持
> 更新日期：2026-11-17
> 核实状态：dnf 通用语义已核实；两发行版仓库地址与模块流命名**未逐版本核实**，以现场 `dnf repolist` 为准

## 技术概念

- **repo 定义**：`/etc/yum.repos.d/*.repo`，包含 `baseurl`/`metalink`、`gpgcheck`、`enabled`。
- **元数据缓存**：`dnf makecache` 拉取仓库元数据；`--refresh` 强制刷新，避免"看到的还是旧版本"。
- **模块（module）**：同一软件多个版本流（如 nodejs 的不同 stream），启用流会影响可安装版本；麒麟/openEuler 对模块化的支持程度不同。
- **dnf history**：每次事务有 ID、命令、变更包、返回码，可用于回退与审计。
- **优先级**：多个仓库提供同名包时，`priority`/`cost` 决定选择；不要靠"先装的赢"。

## 使用场景

- 安装/升级时提示 "no available package" 或版本明显偏旧。
- 需要确认某次升级是谁在什么时候执行的。
- 升级后需要回退到上一个版本。
- 多仓库同时启用导致包来源混乱。

## 操作步骤

1. `dnf repolist` 确认启用的仓库与包数量。
2. `dnf makecache --refresh` 刷新元数据。
3. `dnf info <包名>`、`dnf list --showduplicates <包名>` 看可用版本。
4. 指定版本安装/降级：`dnf install <包名>-<版本>`，必要时 `--allowerasing`（有风险，需评估）。
5. 变更后用 `dnf history` 记录 ID，便于回退。

## 命令示例

```bash
dnf repolist
dnf makecache --refresh

dnf info <包名>
dnf list --showduplicates <包名>
dnf repoquery -l <包名> | head

# 指定版本（版本号必须与仓库中完全一致）
dnf install -y <包名>-<版本>-<release>

# 回退到上一个事务
dnf history
dnf history info <ID>
dnf history undo <ID>

# 模块（若发行版仓库支持）
dnf module list
dnf module enable <模块>:<流>
```

## 预期输出及其含义（示意，非本机实测）

```text
$ dnf repolist
repo id              repo name                          status
OS                   openEuler 24.03 LTS OS             12,345
everything           openEuler 24.03 LTS everything       8,901
```

- `status` 为 0 或明显偏少，说明仓库不可达或元数据未拉取；先排查网络/证书，不要怀疑包本身。

```text
$ dnf list --showduplicates nginx
Available Packages
nginx.x86_64  1.20.1-16.oe2403  OS
nginx.x86_64  1.26.1-1.oe2403   update
```

- 两个版本同时可见时，`dnf upgrade` 默认取最新；若业务需要固定版本，应使用版本锁定或本地仓库，而不是反复手工降级。

## 常见错误

| 现象 | 常见原因 | 处理方向 |
|---|---|---|
| `Failed to download metadata` | 仓库地址不可达、DNS/代理、TLS 证书 | `curl -I <baseurl>` 验证，再 `dnf --refresh` |
| `no available package` | 仓库未启用、模块流未启用、架构不匹配 | `repolist`、`module list`、`dnf --disableexcludes` 排查 |
| 包版本回退又被升回去 | 有更高优先级仓库/自动升级 | 固定版本或排除规则，评估后再做 |
| `history undo` 失败 | 事务包含不可回退操作或包已不可得 | 以快照/备份恢复为准，不要强行伪造仓库 |

## 排查思路

「仓库是否可达 → 元数据是否新 → 包是否在仓库 → 版本/架构是否匹配 → 模块/优先级是否限制」。不要用 `--skip-broken` 掩盖依赖问题。

## 安全注意事项

- `--allowerasing` 可能移除现有包，执行前先 `--assumeno` 预演。
- 不要为省事关掉 `gpgcheck`；第三方仓库必须单独评估并限制优先级。
- 回退事务前确认业务有备份；`history undo` 不是数据库快照。

## 未核实与版本差异

- openEuler 与麒麟 V10 的默认仓库地址、镜像站、模块化支持、`dnf` 版本区间不同，本文不宣称具体 URL 或流名称。
- 两发行版是否启用 `dnf-automatic` 自动升级，未核实。
