# 进程、信号与退出码基础

> 来源类型：自写整理（self_written）
> 来源说明：依据 Linux 信号语义与 systemd 单元行为整理
> 适用版本：通用（systemd 239+）
> 来源链接：https://man7.org/linux/man-pages/man7/signal.7.html
> 适用系统：linux_generic
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## 常用信号
- `SIGTERM(15)`：请求优雅退出，服务应释放端口与临时文件。
- `SIGKILL(9)`：不可捕获，仅用于无法退出的进程；会跳过清理逻辑。
- `SIGHUP(1)`：多数守护进程用于重载配置，而非重启。

## 退出码判读
- 退出码 0 表示成功；1 通常是应用自定义的通用失败。
- systemd 记录 `status=1/FAILURE` 时，含义是主进程以 1 退出，而不是 systemd 自身故障。
- `Result: exit-code` 与 `Result: timeout` 需要区分：后者多为启动超时（`TimeoutStartSec`）。

## 进程树
Supervisor 托管的程序在 `supervisord` 之下；systemd 托管的服务在独立 cgroup 中。排查"进程不见了"时先确认托管者，再决定看 `supervisorctl status` 还是 `systemctl status`。

## 安全注意事项

- `kill -9` 会跳过清理逻辑，可能留下锁文件与半写数据；优先 `SIGTERM` 并观察退出。

## 预期输出与判读

- 信号发出不等于进程已停止，需用 `ps`/`systemctl status` 确认最终状态。

## 常见错误

- `Operation not permitted`：目标进程属于其他用户或受保护，不能随意 kill。
- 进程处于 `D` 状态时信号无效，需先解决 I/O 阻塞。
- 退出码 137 常见于 SIGKILL/OOM，不等于应用自己返回 137。

## 排查思路

- `ps -o pid,ppid,stat,cmd` 看进程树与状态；`D` 状态优先查 I/O。
- 结合 `journalctl -u` 与 `dmesg` 判断是应用退出还是内核杀进程。
