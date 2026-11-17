# openEuler 24.03 LTS 基线要点

> 来源类型：公开资料摘要（public_summary）
> 来源说明：依据 openEuler 社区公开发布的版本说明与通用文档整理，未引用厂商内部材料
> 适用版本：openEuler 24.03 LTS / LTS-SP1
> 来源链接：https://docs.openeuler.org/
> 适用系统：openeuler
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## 版本识别
- `cat /etc/openvista-release` 不适用于 openEuler，应使用 `cat /etc/os-release` 与 `rpm -q openEuler-release`。
- 内核包名形如 `kernel-<版本>.oe2403.<arch>`，`uname -r` 与 `rpm -q kernel` 应对应同一版本。

## 软件包与仓库
- 默认使用 dnf；`dnf repoquery` 可查仓库内可用版本，适合判断"仓库是否提供匹配模块包"。
- 升级前建议 `dnf check-update` 与 `dnf distro-sync` 评估差异；跨大版本升级需单独评估。

## 系统服务
- 使用 systemd；`systemctl list-units --failed` 快速列出失败单元。
- 修改单元后 `systemctl daemon-reload` 是必需的，否则旧配置仍生效。

## 说明
以上为公开资料层面的通用结论，具体补丁级别与软件版本以目标机器 `dnf info` 输出为准。

## 安全注意事项

- 发行版基线只描述公开版本信息；仓库地址、组件默认值以目标机 `dnf repolist` 与 `rpm -q` 为准。

## 预期输出与判读

- `.oe2403` 等标识只用于识别构建来源，不代表与麒麟 V10 行为一致。

## 常见错误

- 把其他发行版的仓库文件直接放进 `/etc/yum.repos.d/`：签名/元数据不匹配，可能装错包。
- 只凭 `/etc/os-release` 的 NAME 判断行为一致：NAME 不覆盖默认策略差异。
- 忽略 `dnf repolist` 为 0：先修网络/证书，不要怀疑包名。

## 排查思路

- 先取基线：`cat /etc/os-release`、`uname -r`、`dnf --version`。
- 再看仓库与包 NEVRA；结论附命令输出。
