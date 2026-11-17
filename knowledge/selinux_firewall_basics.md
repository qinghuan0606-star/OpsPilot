# SELinux 与防火墙基础

> 来源类型：自写整理（self_written）
> 来源说明：依据 SELinux 与 firewalld 公开文档整理
> 适用版本：openEuler 24.03 / 麒麟 V10（默认策略可能有差异）
> 来源链接：https://firewalld.org/documentation/
> 适用系统：linux_generic
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## SELinux 状态
- `getenforce` 返回 `Enforcing` / `Permissive` / `Disabled`。
- 临时切换 `setenforce 0` 只用于验证假设，重启后恢复；生产不建议长期关闭。

## 常见拦截
- 非标准端口需 `semanage port -a -t http_port_t -p tcp <port>` 放行。
- 自定义目录需正确打标签：`semanage fcontext -a -t httpd_sys_content_t <path>` 后 `restorecon -Rv`。

## firewalld
- `firewall-cmd --list-all` 查看当前 zone 规则；`--add-port` 为临时，`--permanent` 后需 `--reload`。

## 判读
"服务正常但访问被拒"优先检查 SELinux 审计日志 `/var/log/audit/audit.log` 中的 `denied` 记录，再检查防火墙规则。

## 安全注意事项

- 禁止长期 `setenforce 0` 或关闭 firewalld；应使用精确策略并记录变更。

## 预期输出与判读

- `getenforce=Permissive` 仍会记录拒绝；不能据此判定策略已正确。

## 常见错误

- `setenforce 0` 作为修复：重启后反弹且掩盖策略问题。
- 只开防火墙端口不看 SELinux：仍可能被拒绝。
- 忽略审计日志：`ausearch -m avc` 才有具体拒绝证据。

## 排查思路

- `getenforce` → `ausearch`/`journalctl` → 精确策略。
- firewalld 用 `--list-all` 核对 zone 与来源。
