# Logstash 日志采集：pipeline、过滤与写入失败排查

> 来源类型：public_summary（公开资料摘要）
> 来源说明：依据 Elastic 官方 Logstash 文档公开的 input/filter/output 语义整理，未复制原文
> 来源链接：https://www.elastic.co/guide/en/logstash/current/index.html
> 适用系统：Linux 通用（RPM 或容器部署）
> 适用版本：Logstash 7.x / 8.x
> 更新日期：2026-11-17
> 核实状态：pipeline 语义已核对公开文档；两发行版上的安装包、JDK 依赖与默认路径**未实测**

## 技术概念

- **三段式 pipeline**：`input`（读源）→ `filter`（解析/改写）→ `output`（写目标）。三个插件各有独立队列与线程。
- **持久化队列（PQ）**：`queue.type: persisted` 可在进程重启时保留事件；默认内存队列丢事件。
- **事件结构与 `@timestamp`**：`filter` 里的 `date` 决定写入 ES 的时间字段；解析失败会落到 `_grokparsefailure` 标签。
- **条件分支**：`if [type] == "nginx"`、`if "_grokparsefailure" in [tags]` 可把异常事件分流到独立索引，避免污染主索引。
- **背压**：ES 写入慢会导致 pipeline 阻塞，表现为 input 读得慢或队列堆积；不是"Logstash 卡死"。

## 使用场景

- 应用日志无法进入 ES，需要判断是采集、解析还是写入环节。
- 日志时间字段错乱、字段缺失、grok 解析失败。
- 需要为不同服务分流到不同索引。
- 重启后日志丢失，需要启用持久化队列。

## 操作步骤

1. `systemctl status logstash` / 容器日志确认进程与配置加载。
2. 用 `bin/logstash -f <conf> --config.test_and_exit` 校验配置语法。
3. 看 Logstash 自身日志中的 pipeline 统计（`events_in`/`events_out`/`duration_in_millis`）。
4. 检查 grok 是否匹配：先在 `filter` 中加 `_grokparsefailure` 分流，观察异常索引。
5. 检查 output 侧 ES 是否 429/只读/认证失败。

## 配置示例（仅示意）

```ruby
input {
  beats { port => 5044 }
}

filter {
  if [fields][service] == "app-worker" {
    grok {
      match => { "message" => "%{TIMESTAMP_ISO8601:log_time} %{LOGLEVEL:level} %{GREEDYDATA:msg}" }
    }
    date { match => ["log_time", "ISO8601"] }
  }
  if "_grokparsefailure" in [tags] {
    mutate { add_field => { "[@metadata][index_suffix]" => "parse-failure" } }
  }
}

output {
  if "_grokparsefailure" in [tags] {
    elasticsearch {
      hosts => ["http://<es-host>:9200"]
      index => "app-parse-failure-%{+YYYY.MM.dd}"
    }
  } else {
    elasticsearch {
      hosts => ["http://<es-host>:9200"]
      index => "app-logs-%{+YYYY.MM.dd}"
    }
  }
}
```

## 命令示例

```bash
# 配置语法检查（不启动 pipeline）
/usr/share/logstash/bin/logstash -f /etc/logstash/conf.d/app.conf --config.test_and_exit

# 查看服务日志
journalctl -u logstash --since "15 min ago" --no-pager

# 若启用监控 API（示意）
curl -s "http://<logstash-host>:9600/_node/stats/pipelines?pretty"
```

## 预期输出及其含义（示意，非本机实测）

```text
[INFO ] [logstash.agent] Pipelines running {:count=>1, :running_pipelines=>[:main]}
```

- 只代表 pipeline 已启动，不代表事件写入成功；必须看 `events_out` 与 ES 侧文档数。

```text
"events" => {"in" => 10234, "filtered" => 10234, "out" => 9800}
```

- `out < filtered` 说明 output 有失败/重试；结合 ES 429 或认证错误判断。

## 常见错误

| 现象 | 常见原因 | 判断 |
|---|---|---|
| 配置检查通过但无数据 | input 未收到事件、beats 端口不通 | `ss -lntp`、filebeat 日志 |
| 字段缺失 | grok 未匹配、`remove_field` 误删 | `_grokparsefailure`、`stdout { codec => rubydebug }` 调试 |
| 时间字段不对 | `date` 未设置或格式不匹配 | 查 ES 中 `@timestamp` 与原始字段 |
| ES 429 / 只读 | ES 写入压力或磁盘水位 | ES `_cluster/health`、`_cat/allocation` |
| 重启丢日志 | 内存队列 | 评估 `queue.type: persisted` 与磁盘容量 |

## 排查思路

「input 是否有事件 → filter 是否解析成功 → output 是否成功」。三段分别用监控 API/日志/ES 侧计数验证，不要只看一段。

## 安全注意事项

- Beats/Logstash 端口不要暴露公网；启用 TLS 与共享密钥。
- 调试时 `rubydebug` 会打印完整事件，可能含敏感字段，禁止长期开启。
- 不要把解析失败的原始日志直接丢弃；分流保留便于定位。
- 本文不含任何删除队列或清空索引的操作。

## 未核实与版本差异

- openEuler 与麒麟 V10 默认 JDK 版本、Logstash 是否在默认仓库提供、默认配置目录（`/etc/logstash/conf.d` vs 其他）未实测。
- Logstash 8.x 默认 ECS 兼容模板与 7.x 行为不同，未逐版本展开。
