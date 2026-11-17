# 日志采集链路与故障定位（Filebeat → Logstash → Elasticsearch → Kibana）

> 来源类型：self_written（自写整理）
> 来源说明：依据 Elastic 官方公开文档的组件职责与 `journalctl`/`rsyslog` 通用语义整理，链路图为自绘
> 来源链接：https://www.elastic.co/guide/en/beats/filebeat/current/index.html
> 适用系统：Linux 通用（openEuler / 麒麟 V10 均可部署）
> 适用版本：Filebeat 7.x/8.x、Logstash 7.x/8.x、Elasticsearch 7.x/8.x、Kibana 7.x/8.x
> 更新日期：2026-11-17
> 核实状态：组件职责已核对公开文档；具体版本组合与两发行版兼容性**未实测**

## 技术概念

- **链路四段**：采集（Filebeat/rsyslog）→ 传输与解析（Logstash/Beats）→ 存储与索引（ES）→ 查询展示（Kibana）。
- **本机日志三来源**：`journald`（`journalctl`）、`rsyslog`（`/var/log/messages`、`/var/log/secure`）、应用自有文件（`/var/log/<app>/*.log`）。
- **采集位点**：Filebeat 用 registry 记录读取偏移；容器场景需挂载日志目录，否则读到的是容器内路径。
- **失败分层**：采不到（源/权限/路径）→ 解析错（grok/JSON）→ 写不进（ES 429/只读/认证）→ 查不到（索引模式/时间字段）。
- **丢弃与保留**：解析失败事件应分流保留，而不是静默丢弃，否则故障期证据缺失。

## 使用场景

- 某服务日志在 Kibana 里缺失，需要定位断在哪一段。
- 日志平台整体延迟高，需要判断是采集过载还是 ES 写入受限。
- 升级后日志字段变化，解析规则失效。
- 需要确认本机日志到底写在 journald 还是文件。

## 操作步骤

1. 源侧：确认日志确实产生（`journalctl -u <svc> -n 20`、`tail -n 20 <file>`）。
2. 采集侧：确认采集器进程、配置、读取位点与权限（服务用户能否读日志）。
3. 传输侧：Logstash pipeline 事件计数、grok 失败标签。
4. 存储侧：ES 索引是否存在、文档数是否增长、是否 429/只读。
5. 展示侧：Kibana 索引模式与时间字段。
6. 记录断点，再修对应一段。

## 命令示例

```bash
# 1) 源
journalctl -u <svc> -n 20 --no-pager
tail -n 20 /var/log/<app>/app.log
logger -t ops-selftest "pipeline selftest $(date -Is)"   # 写入 syslog 做端到端自测

# 2) 采集
systemctl status filebeat --no-pager
filebeat test config -c /etc/filebeat/filebeat.yml
filebeat test output -c /etc/filebeat/filebeat.yml

# 3) 传输
journalctl -u logstash -n 50 --no-pager

# 4) 存储
curl -s "http://<es-host>:9200/_cat/indices/app-logs-*?v&s=index:desc" | head

# 5) 展示
# Kibana → Data Views 中确认索引模式与 @timestamp
```

## 预期输出及其含义（示意，非本机实测）

```text
$ filebeat test output
elasticsearch: http://<es-host>:9200...
  parse url... OK
  connection... OK
  talk to server... OK
  version: 8.x.x
```

- 只证明 Filebeat 能连上 ES；若实际走 Logstash，还需验证 Logstash 输出段。

```text
$ _cat/indices/app-logs-*
green open app-logs-2026.11.17 3 1 1200000 0 2.1gb 700mb
```

- 文档数不增长时，先看采集位点与解析，再看 ES 写入拒绝；不要直接重建索引。

## 常见错误

| 断点 | 现象 | 常见原因 |
|---|---|---|
| 源 | `journalctl` 有、文件为空 | 应用未写文件、日志被 systemd 接管 |
| 采集 | Filebeat 无输出 | 路径/权限、容器路径未挂载、registry 偏移错乱 |
| 解析 | 字段缺失、`_grokparsefailure` | 日志格式变更、grok 未匹配 |
| 存储 | 429、索引只读 | 写入过载、磁盘水位、mapping 冲突 |
| 展示 | Kibana 空白 | 索引模式名/时间字段不匹配 |

## 排查思路

用一条带唯一标记的自测日志（`logger -t ops-selftest ...`）贯穿全链路，逐段确认"是否到达"。这比反复重启组件有效，也能留下可复核证据。禁止在生产上为排查而清空索引或删除队列。

## 安全注意事项

- 采集器账号只授予读日志与写目标索引的最小权限。
- 日志中可能含令牌、身份证号等，采集链路要配置脱敏与访问控制。
- 不要为排查方便把 ES/Kibana 暴露到公网或关闭认证。
- 自测日志不要包含任何真实业务数据。

## 未核实与版本差异

- openEuler 与麒麟 V10 默认日志组件（rsyslog vs systemd-journald 的持久化配置）不同，`/var/log/messages` 是否存在需现场确认。
- Filebeat/Logstash 在两发行版默认仓库的可用版本未核实。
