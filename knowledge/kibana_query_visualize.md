# Kibana 日志查询与可视化：索引模式、DSL 与故障定位

> 来源类型：public_summary（公开资料摘要）
> 来源说明：依据 Elastic 官方 Kibana 文档公开的索引模式、Discover、KQL 与可视化概念整理
> 来源链接：https://www.elastic.co/guide/en/kibana/current/index.html
> 适用系统：Linux 通用（服务端部署；浏览器访问）
> 适用版本：Kibana 7.x / 8.x
> 更新日期：2026-11-17
> 核实状态：功能语义已核对公开文档；两发行版上的部署与代理配置**未实测**

## 技术概念

- **索引模式（index pattern / data view）**：Kibana 查询的前提，需匹配 ES 中真实存在的索引名，并指定时间字段（通常 `@timestamp`）。
- **KQL 与 DSL**：Discover 使用 KQL（`service: "app-worker" and level: "ERROR"`）；复杂聚合走 DSL 或可视化。
- **字段可用性**：字段未在索引模式中刷新（refresh field list）时，过滤与聚合会"看不到"该字段。
- **时间范围**：Kibana 的时间选择器基于索引模式的时间字段；字段映射错误会导致"明明有日志却查不到"。
- **保存对象**：搜索、可视化、仪表盘都是保存对象，依赖索引模式；索引模式改名/删除会让面板失效。

## 使用场景

- 需要按服务、级别、关键字快速定位一段时间内的错误日志。
- 新建日志索引后，Kibana 里看不到数据。
- 仪表盘突然空白，需要判断是数据问题还是索引模式问题。
- 把一次排查固化为可复用的保存搜索。

## 操作步骤

1. 确认 ES 中存在目标索引：`_cat/indices` 对照 Kibana 索引模式。
2. 在 Stack Management → Data Views 创建/检查索引模式，指定时间字段。
3. Discover 中选择时间范围，先用宽条件（`service: "x"`）确认有数据，再加 `level` 与关键字收窄。
4. 字段不显示时刷新字段列表。
5. 保存搜索/可视化，命名包含服务与用途。

## 命令示例与查询示例（KQL，仅示意）

```text
service: "app-worker" and level: ("ERROR" or "FATAL")
message: "permission denied" or message: "No space left on device"
@timestamp >= "2026-11-17T00:00:00.000+08:00" and @timestamp < "2026-11-17T12:00:00.000+08:00"
```

对应的 DSL 片段（用于 API 验证）：

```json
{
  "query": {
    "bool": {
      "filter": [
        {"term": {"service": "app-worker"}},
        {"range": {"@timestamp": {"gte": "now-30m"}}}
      ],
      "must": [{"match": {"message": "permission denied"}}]
    }
  }
}
```

## 预期输出及其含义（示意，非本机实测）

```text
Discover: 12 hits
@timestamp 2026-11-17T02:11:03.221+08:00  service app-worker  level ERROR  message open /var/log/appops: permission denied
```

- 行数不为 0 只说明"有匹配"，还要看时间范围与字段值是否符合预期；不要用命中数当作故障范围。

## 常见错误

| 现象 | 常见原因 | 判断 |
|---|---|---|
| Discover 无数据但 ES 有文档 | 索引模式名不匹配、时间字段映射错误 | 用 `_cat/indices` 与 `_mapping` 对照 |
| 字段下拉里没有目标字段 | 字段列表未刷新、字段被 mapping 为 text 而非 keyword | 刷新字段；聚合需 keyword |
| 仪表盘空白 | 索引模式被删/改名、时间范围无数据 | 检查保存对象依赖 |
| KQL 语法报错 | 引号/括号/字段名错误 | 先用单一条件验证 |
| 时间显示时区错 | 浏览器时区与数据时区不一致 | 统一用 `@timestamp` 与明确时区 |

## 排查思路

「ES 有无数据 → 索引模式是否匹配 → 时间字段是否正确 → KQL 是否命中 → 字段类型是否支持聚合」。Kibana 只是查询前端，空白通常不是 Kibana 本身故障。

## 安全注意事项

- Kibana 不要直接暴露公网；启用认证并按角色限制索引访问。
- 日志含敏感信息时，避免把原始日志分享到公开仪表盘。
- 保存搜索与仪表盘命名不要包含主机密码、内网地址等敏感信息。
- 本文不含任何绕过认证或越权查询的做法。

## 未核实与版本差异

- Kibana 7.x 的 "Index Patterns" 在 8.x 中改称 "Data Views"，界面路径不同；本文按概念描述，未逐版本截屏。
- openEuler/麒麟 V10 上的部署方式与代理（Nginx）配置未实测。
