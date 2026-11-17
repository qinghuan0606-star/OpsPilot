# systemd unit 文件：依赖、重启策略与沙箱

> 来源类型：self_written（自写整理）
> 来源说明：依据 `systemd.unit(5)`、`systemd.service(5)`、`systemd.exec(5)`、`systemctl(1)` 的公开 man page 语义整理
> 来源链接：https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
> 适用系统：systemd 系 Linux（openEuler 与麒麟 V10 均使用 systemd）
> 适用版本：systemd 239+（麒麟 V10 与 openEuler 24.03 的具体小版本未核实）
> 更新日期：2026-11-17
> 核实状态：指令语义已核实；两发行版默认启用的沙箱项与内核版本差异**未逐版本核实**

## 技术概念

- **unit 三段**：`[Unit]` 描述与依赖，`[Service]` 启动方式与重启策略，`[Install]` 开机启用关系。
- **启动类型**：`Type=simple`（ExecStart 即主进程）、`forking`（需 `PIDFile`）、`notify`（需应用支持 sd_notify）、`oneshot`（一次性）。
- **依赖语义**：`After=` 只影响顺序，不保证对方成功；`Requires=` 保证对方启动但不会自动拉起本服务；`Wants=` 是弱依赖。
- **重启**：`Restart=on-failure` + `RestartSec=` + `StartLimitIntervalSec/StartLimitBurst` 共同决定"重启风暴"是否被 systemd 拦下。
- **沙箱**：`ProtectSystem`、`ProtectHome`、`PrivateTmp`、`NoNewPrivileges`、`ReadWritePaths=` 会在排查权限问题时制造"看不见的拒绝"。

## 使用场景

- 编写/修改服务 unit，需要正确的启动类型与重启策略。
- 服务启动失败、反复重启被 systemd 放弃（`start-limit-hit`）。
- 升级后 unit 被覆盖，需要区分 `/usr/lib/systemd/system` 与 `/etc/systemd/system`。
- 权限类报错，但文件权限看起来正常（沙箱限制）。

## 操作步骤

1. 确认 unit 来源与优先级：`systemctl cat`、`systemctl show -p FragmentPath`。
2. 用 `systemd-analyze verify <unit>` 静态校验语法与依赖。
3. 本地覆盖用 `systemctl edit <unit>` 生成 drop-in，不直接改包自带文件。
4. `daemon-reload` 后 `restart`，再用 `status` 与 `journalctl` 验证。
5. 观察重启计数与 `start-limit-hit`，避免无限重启。

## 命令示例

```bash
systemctl cat <unit>
systemctl show -p FragmentPath -p DropInPaths <unit>
systemd-analyze verify /etc/systemd/system/<unit>

# 安全的本地覆盖
systemctl edit <unit>          # 生成 /etc/systemd/system/<unit>.d/override.conf
systemctl daemon-reload
systemctl restart <unit>
systemctl status <unit> --no-pager -l

# 查看失败与重启次数
systemctl show -p NRestarts -p Result <unit>
journalctl -u <unit> --since "30 min ago" --no-pager
```

## unit 示例（仅示意，路径需按实际程序调整）

```ini
[Unit]
Description=Example ops worker
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=appops
Group=appops
WorkingDirectory=/var/lib/appops
ExecStart=/usr/local/bin/app-worker --config /etc/appops/worker.conf
Restart=on-failure
RestartSec=5s
TimeoutStopSec=30s
LimitNOFILE=65535
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

## 预期输出及其含义（示意，非本机实测）

```text
$ systemctl status <unit>
● <unit> - Example ops worker
   Loaded: loaded (/etc/systemd/system/<unit>; enabled; preset: disabled)
   Active: failed (Result: exit-code) since ...
   Process: 1234 ExecStart=/usr/local/bin/app-worker ... (code=exited, status=2)
```

- `Loaded:` 路径决定你改的文件是否是生效文件；改错目录会出现"改了没效果"。
- `status=2` 是应用自己的退出码，需要对照应用文档，不是 systemd 错误。

```text
$ systemctl show -p Result -p NRestarts <unit>
Result=start-limit-hit
NRestarts=5
```

- `start-limit-hit` 表示在 `StartLimitIntervalSec` 窗口内达到 `StartLimitBurst`，systemd 已停止继续拉起；此时应先修根因，再 `systemctl reset-failed`。

## 常见错误

| 现象 | 常见原因 |
|---|---|
| `Unit not found` | unit 不在搜索路径，或文件名拼错（必须含后缀） |
| `Exec format error` | 二进制架构不匹配、脚本缺 shebang、缺执行位 |
| `status=203/EXEC` | `ExecStart` 路径不存在/不可执行/SELinux 拒绝 |
| `status=226/NAMESPACE` | 沙箱项与运行环境冲突（`ProtectSystem`、`PrivateTmp`） |
| 反复重启 `start-limit-hit` | 应用启动即崩溃，重启策略掩盖了根因 |

## 排查思路

先 `systemctl cat` 确认实际生效配置 → `systemd-analyze verify` 排除语法 → `status` 看退出码与 Result → `journalctl -u` 看应用侧日志 → 若权限类报错，逐个排除 `Protect*`/`ReadWritePaths`/SELinux。不要一上来改 `Restart=always`。

## 安全注意事项

- 不要用 `Restart=always` 掩盖启动失败；先修根因。
- 不要以 root 运行应用；配合 `User=`、`NoNewPrivileges=true`。
- 直接改 `/usr/lib/systemd/system` 下的包自带 unit 会被升级覆盖，应使用 drop-in。
- 本文不提供任何关闭 SELinux/防火墙的"修复"步骤。

## 未核实与版本差异

- 麒麟 V10 的 systemd 版本较老，部分指令（如 `RestartMode=`、`ProtectProc=`）可能不支持，需 `man systemd.service` 现场确认。
- openEuler 24.03 的默认 `DefaultTimeoutStopSec` 与沙箱默认值未逐版本核实。
