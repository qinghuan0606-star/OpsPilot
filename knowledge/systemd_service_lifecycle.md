# systemd 服务生命周期与失败排查

> 来源类型：自写整理（self_written）
> 来源说明：依据 systemd 官方文档与通用发行版行为整理
> 适用版本：systemd 239+（openEuler 24.03 / 麒麟 V10 适用）
> 来源链接：https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
> 适用系统：linux_generic
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## 状态语义
- `active (running)`：主进程在运行。
- `failed`：启动或运行失败，`systemctl status` 会给出退出码与最近日志。
- `inactive (dead)`：正常停止，不等于失败。

## 排查顺序
1. `systemctl status <unit>` 看 `Result` 与 `status=`。
2. `journalctl -u <unit> -n 80 --no-pager` 看启动阶段报错。
3. `systemctl cat <unit>` 确认 `ExecStart`、`EnvironmentFile` 与 `User` 是否符合预期。
4. 关注 `restart_count` 与 `StartLimitBurst`：反复重启会触发 start-limit，此时需要 `systemctl reset-failed`。

## 配置变更
修改 unit 文件后，`systemctl daemon-reload` 是必须步骤；只 `restart` 不会重新加载 unit 定义。

## 安全注意事项

- 不要用 `Restart=always` 掩盖启动失败；先修根因再谈重启策略。

## 预期输出与判读

- `active (running)` 只表示主进程在跑，业务可用性仍需端口/健康检查佐证。

## 常见错误

- 改错 unit 目录（`/usr/lib` 被升级覆盖）：应使用 drop-in。
- 看到 `failed` 就 `restart`：先读退出码与 journal。
- 用 `Restart=always` 掩盖崩溃：会形成重启风暴。

## 排查思路

- `systemctl cat` 确认生效配置 → `status` 看退出码 → `journalctl -u` 看应用日志。
- 权限类报错再查沙箱项与 SELinux。
