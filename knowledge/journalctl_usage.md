# journalctl 日志检索

> 来源类型：自写整理（self_written）
> 来源说明：依据 systemd-journald 文档整理
> 适用版本：systemd 239+
> 来源链接：https://www.freedesktop.org/software/systemd/man/latest/journalctl.html
> 适用系统：linux_generic
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## 常用过滤
- `journalctl -u nginx -n 100 --no-pager`：指定单元最近 100 行。
- `journalctl -p err -b`：本次启动以来的 err 及以上级别。
- `journalctl --since "10 min ago"`：按时间窗过滤，适合和故障时间点对齐。

## 级别
`emerg(0) > alert(1) > crit(2) > err(3) > warning(4) > notice(5) > info(6) > debug(7)`。
`emerg` 常见于模块加载失败、内存分配失败等致命错误。

## 持久化
默认可能只在 `/run/log/journal` 保存本次启动日志；需要跨重启保留时，应确认 `/var/log/journal` 是否存在并启用持久化存储。

## 判读原则
日志只能证明"发生了什么"，不能单独证明"为什么"；归因需要与包版本、依赖状态、配置内容交叉验证。

## 安全注意事项

- 日志可能含令牌与个人信息，导出与分享前需脱敏。

## 预期输出与判读

- 日志只能证明发生了什么，不能单独证明原因；归因要结合包版本与配置。

## 常见错误

- 只看最后几行：故障前的上下文丢失，应用 `--since` 对齐时间窗。
- 把 `-p err` 当全部错误：应用可能用 warning 记录关键信息。
- 忽略持久化配置：重启后日志消失导致无法复盘。

## 排查思路

- 按时间窗 + 单元 + 级别三层过滤。
- 日志与包版本、配置、依赖状态交叉验证。
