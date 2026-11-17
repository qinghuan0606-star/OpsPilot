# Supervisor：进程守护、自动重启与日志

> 来源类型：self_written（自写整理）
> 来源说明：依据 Supervisord 官方文档（配置项语义）整理，命令输出为按语义构造的示意
> 来源链接：http://supervisord.org/configuration.html
> 适用系统：Linux 通用（openEuler / 麒麟 V10 均可安装 Supervisor）
> 适用版本：Supervisor 4.x（Python 3 环境）
> 更新日期：2026-11-17
> 核实状态：配置项语义已核实；两发行版是否默认预装、发行版打包路径**未逐版本核实**

## 技术概念

- **supervisord 是父进程**：它按配置拉起 `program`，监控退出并重试；本身通常由 systemd 托管。
- **`autorestart`**：`true`/`false`/`unexpected`。`unexpected` 表示只有非 `exitcodes` 的退出才重启，是更可控的默认。
- **`startretries` + `startsecs`**：进程启动后存活不足 `startsecs` 视为启动失败，最多重试 `startretries` 次，超过进入 `FATAL`。
- **日志分流**：`stdout_logfile`、`stderr_logfile` 由 supervisor 接管；`childlogdir` 影响子进程；`logfile_maxbytes` 与 `logfile_backups` 决定轮转。
- **控制通道**：`supervisorctl` 通过 `[unix_http_server]`/`[inet_http_server]` 与 daemon 通信；socket 权限错误会导致 `unix:///var/run/supervisor.sock no such file` 或 `permission denied`。

## 使用场景

- 非 systemd 管理的常驻进程（Java/Python worker、队列消费者）需要自动拉起。
- 进程反复退出，需要看是启动失败（FATAL）还是运行中崩溃。
- 需要区分"supervisor 没重启"与"进程启动即崩"。
- 日志被 supervisor 接管，排查应用日志位置。

## 操作步骤

1. `supervisorctl status` 看状态与描述（`RUNNING`/`FATAL`/`BACKOFF`）。
2. 读 `/etc/supervisord.conf` 或 `conf.d/*.ini`，确认 `autorestart`、`startretries`、`exitcodes`、`user`。
3. 看 supervisor 自身日志（`logfile`）与 program 的 `stderr_logfile`。
4. 手工以相同用户/环境执行 `command`，复现退出码。
5. 修好后 `supervisorctl reread && supervisorctl update`，再 `start <program>`。

## 配置示例（仅示意）

```ini
[program:app-worker]
command=/usr/local/bin/app-worker --config /etc/appops/worker.conf
directory=/var/lib/appops
user=appops
autostart=true
autorestart=unexpected
exitcodes=0
startsecs=5
startretries=3
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/appops/worker.out.log
stderr_logfile=/var/log/appops/worker.err.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
environment=APP_ENV="prod",LANG="en_US.UTF-8"
```

## 命令示例

```bash
supervisorctl status
supervisorctl status app-worker
supervisorctl tail -100 app-worker stderr
supervisorctl reread
supervisorctl update
supervisorctl restart app-worker
supervisorctl avail
```

## 预期输出及其含义（示意，非本机实测）

```text
$ supervisorctl status app-worker
app-worker                       FATAL     Exited too quickly (process log may have details)
```

- `FATAL + Exited too quickly`：进程在 `startsecs` 内退出且重试次数用尽。**不是** supervisor 不工作，而是应用启动即失败。
- 若状态是 `BACKOFF`：正在按退避间隔重试，说明还在重试窗口内。

```text
$ supervisorctl tail -100 app-worker stderr
... ERROR: config /etc/appops/worker.conf: permission denied
```

- 这类输出说明是应用侧文件权限问题；supervisor 的重启策略无法修复。

## 常见错误

| 现象 | 常见原因 | 处理方向 |
|---|---|---|
| `FATAL Exited too quickly` | 启动即崩、依赖未就绪、配置路径错 | 手工以 `user` 身份执行 command |
| 进程运行中崩溃但不重启 | `autorestart=false`，或退出码在 `exitcodes` 内被视作正常 | 调整策略前先确认业务语义 |
| `unix:///... no such file` | supervisord 未启动、socket 路径不一致、权限不足 | 查 `supervisord -c` 配置与进程 |
| 改了 ini 不生效 | 只改了文件，没有 `reread/update` | 按顺序执行并看返回 |
| 日志不写 | 目录权限、`stdout_logfile=NONE`、轮转配置 | 检查 `user` 与目录属主 |

## 排查思路

「supervisor 是否在跑 → 配置是否被加载 → 进程状态 → 进程日志 → 同用户手工复现」。重启次数只能说明"试过几次"，不能说明"为什么失败"。

## 安全注意事项

- socket 不要暴露到公网；`[inet_http_server]` 若启用必须绑定回环并设认证。
- 不要用 root 运行 program；`user=` 指定低权账号。
- 日志可能含敏感参数，轮转与留存要符合审计要求。
- 本文不提供任何"无限重启掩盖故障"的配置建议。

## 未核实与版本差异

- openEuler 与麒麟 V10 的默认 Python 版本、Supervisor 是否可从默认仓库安装、默认配置路径（`/etc/supervisord.conf` vs `/etc/supervisor/supervisord.conf`）未逐版本核实。
- 部分发行版默认由 systemd 托管 supervisord，unit 名称可能不同，需现场 `systemctl list-unit-files | grep supervisor`。
