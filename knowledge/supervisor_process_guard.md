# Supervisor 进程托管

> 来源类型：自写整理（self_written）
> 来源说明：依据 Supervisor 官方文档整理
> 适用版本：Supervisor 4.x
> 来源链接：http://supervisord.org/
> 适用系统：linux_generic
> 更新日期：2026-11-17
> 核实状态：通用语义已核对公开资料；发行版默认值需现场取证

## 状态
- `supervisorctl status` 显示 `RUNNING` / `FATAL` / `BACKOFF` 等状态。
- `FATAL` 常见于 `startretries` 用尽，含义是子进程连续启动失败，而不是 supervisord 本身挂了。

## 配置要点
- `autorestart=true` 与 `startsecs` 配合决定"启动成功"的判定窗口；`exitcodes` 需按业务约定设置。
- 程序日志位置由 `stdout_logfile` 决定，与 journal 分离；排查时要同时看这两处。

## 与 systemd 的关系
Supervisor 自身通常由 systemd 托管；因此"服务起不来"可能出现在两层：systemd 层的 `supervisord` 与 supervisor 层的业务进程。

## 安全注意事项

- 不要以 root 运行 program；socket 不要暴露到公网。

## 预期输出与判读

- `RUNNING` 不代表业务健康；`FATAL` 常见原因是启动即退出，应看 program 的 stderr 日志。

## 常见错误

- `FATAL` 就判定 supervisor 故障：多为 program 启动即退出。
- 改配置不 `reread/update`：新配置未加载。
- 以 root 运行 program：权限过大且日志属主混乱。

## 排查思路

- status → program stderr → 同用户手工执行 command。
- 区分启动失败与运行中崩溃，再看重启策略是否合理。
