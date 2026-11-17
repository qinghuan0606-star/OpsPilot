# Linux 常用命令速查（基础）

> 来源类型：自写整理（self_written）
> 来源说明：依据 Linux 通用 man page 与 POSIX 常见行为整理，未引用任何厂商内部文档
> 适用版本：通用（openEuler 24.03 / 麒麟 V10 SP3 均适用）
> 来源链接：https://man7.org/linux/man-pages/
> 适用系统：linux_generic
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## 文件与目录
- `ls -lh` 按人类可读单位列目录；`ls -lZ` 同时显示 SELinux 上下文。
- `cp -a` 保留权限、时间戳与链接；跨文件系统拷贝时注意 ACL 与 xattr 是否保留。
- `mv` 在同一文件系统内是重命名，跨文件系统等价于拷贝后删除。

## 进程与服务
- `ps -ef` 查看全量进程；`ps -eo pid,ppid,stat,pcpu,pmem,cmd` 便于定位资源占用。
- `top -b -n1` 适合脚本化采样；交互态按 `1` 可展开每核使用率。
- `systemctl status <unit>` 展示主进程、最近日志与退出码，比只看 `is-active` 更有信息量。

## 文本与日志
- `grep -n -E` 支持扩展正则；大文件优先 `grep -m` 限制命中条数。
- `journalctl -u <unit> -n 50 --no-pager` 取最近 50 行；`-p err` 只看 err 及以上。
- `tail -F` 跟踪滚动日志，比 `tail -f` 更能应对日志轮转。

## 使用边界
命令参数含义以目标系统的 man page 为准；不同发行版的默认值可能不同，例如 `journalctl` 的持久化配置。

## 安全注意事项

- 命令速查用于定位，不替代变更评审；`rm`、`chmod -R`、`dd` 等破坏性命令必须先确认路径与备份。

## 预期输出与判读

- 输出中的单位、权限位与时间戳都可能因 locale 变化；判读时以字段含义为准，不要只看颜色或中文翻译。

## 常见错误

- `command not found`：命令未安装或 PATH 不含该目录，用 `command -v` 确认；不要盲目 `export PATH=.`。
- `Argument list too long`：通配符展开超过内核限制，改用 `find -exec` 或 `xargs`。
- `Text file busy`：可执行文件正在运行仍被覆盖，先停服务再替换。

## 排查思路

- 先用 `command -v`/`type` 判断命令是否存在，再看 man page 的参数语义。
- 涉及删除/覆盖时先用 `ls` 与 `stat` 确认目标，再执行。
