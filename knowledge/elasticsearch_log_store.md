# Elasticsearch 日志存储：索引、分片与写入排查

> 来源类型：public_summary（公开资料摘要）
> 来源说明：依据 Elastic 官方文档公开的索引/分片/集群概念整理，未复制原文；具体参数以现场版本为准
> 来源链接：https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html
> 适用系统：Linux 通用（容器或 RPM 部署均可）
> 适用版本：Elasticsearch 7.x / 8.x（两代 API 有差异，本文标注差异点）
> 更新日期：2026-11-17
> 核实状态：概念与常用 API 已核对公开文档；openEuler/麒麟 V10 上的部署包与默认 JVM 参数**未实测**

## 技术概念

- **索引（index）= 一类日志的容器**：日志场景常按时间切分（如 `app-logs-2026.11.17`），配合 ILM 做滚动与过期删除。
- **主分片与副本**：主分片数在创建时固定，后期改需 `_shrink`/重建；副本数可动态调整。单节点集群副本无法分配，集群状态会显示 `yellow`。
- **refresh 与 flush**：`refresh` 让文档可被搜索（默认 1s），`flush` 落盘并清 translog；写入压力大时可适度增大 `refresh_interval`。
- **mapping**：字段类型一旦写入再改会冲突（如 `status` 先数字后字符串），日志采集应使用 index template 固定字段。
- **磁盘水位**：低/高/洪水三档水位会触发只读或分片迁移，写入失败常与磁盘水位有关。

## 使用场景

- 应用日志写入 ES 失败、索引变红/黄。
- 查询某时间段日志返回为空或字段无法聚合。
- 日志索引无限增长，需要生命周期管理。
- 集群磁盘告警导致分片无法分配。

## 操作步骤

1. `_cluster/health` 看整体状态；`yellow` 通常是副本未分配，`red` 是主分片未分配。
2. `_cat/indices?v` 看索引大小、文档数、健康。
3. `_cat/shards?v` 定位未分配分片与节点。
4. 写入失败时看 `_cluster/allocation/explain` 与节点日志（磁盘水位、mapping 冲突）。
5. 查询验证用 `_search`，先小范围时间过滤，避免全索引扫描。

## 命令示例

```bash
# 集群与索引概览
curl -s "http://<es-host>:9200/_cluster/health?pretty"
curl -s "http://<es-host>:9200/_cat/indices?v&s=store.size:desc"
curl -s "http://<es-host>:9200/_cat/shards?v"

# 分片未分配原因
curl -s -XGET "http://<es-host>:9200/_cluster/allocation/explain?pretty" -H 'Content-Type: application/json' -d '{}'

# 查询最近日志（示意字段）
curl -s -XGET "http://<es-host>:9200/app-logs-*/_search?pretty" -H 'Content-Type: application/json' -d '{
  "size": 5,
  "query": {"bool": {"filter": [
    {"term": {"service": "app-worker"}},
    {"range": {"@timestamp": {"gte": "now-15m"}}}
  ]}}
}'
```

## 预期输出及其含义（示意，非本机实测）

```text
$ curl .../_cluster/health
{"cluster_name":"ops-log","status":"yellow","number_of_nodes":1,
 "active_primary_shards":12,"active_shards":12,"unassigned_shards":12}
```

- 单节点 + 副本数 1 → 12 个副本分片无法分配，`yellow` 属预期；不是数据丢失。
- `status=red` 且 `unassigned_shards` 包含主分片，才需要立即处理。

```text
$ _cat/indices
green open app-logs-2026.11.17  3 1  1200000 0  2.1gb  700mb
```

- `docs.count` 与 `store.size` 可用于判断是否需要 ILM 滚动；不要用"索引多"直接判定性能问题。

## 常见错误

| 现象 | 常见原因 | 判断方式 |
|---|---|---|
| 写入 429 `es_rejected_execution_exception` | 写入队列/线程池打满 | 降低采集速率、增加节点、调整批量 |
| 索引只读 | 磁盘达到洪水水位 | `_cat/allocation?v`、节点日志 |
| `mapper_parsing_exception` | 字段类型冲突 | 查看 index template 与已有 mapping |
| 查询无结果但索引有文档 | 时间字段映射错、时区/格式不一致 | `_mapping`、`_search` 按 `match_all` 验证 |
| 集群 `red` | 主分片无法分配、节点离线、路径不可写 | `allocation/explain` |

## 排查思路

先集群健康与分片分配，再磁盘水位，再 mapping 与查询条件，最后才怀疑采集端。写入链路问题要同时看采集端（Logstash/Filebeat）与 ES 两侧日志。

## 安全注意事项

- 9200 不要直接暴露公网；启用认证与 TLS，按角色最小授权。
- 日志可能含个人信息与凭据，索引生命周期与访问权限要配套。
- 不要用 `curl -XDELETE /*` 清索引；删除必须精确到索引名并先确认保留策略。
- 本文不含任何清空集群的操作。

## 未核实与版本差异

- ES 7.x 与 8.x 在安全默认（8.x 默认开启 security）、API 路径与客户端兼容性上不同，本文未逐版本展开。
- openEuler 与麒麟 V10 上的 RPM 包/容器镜像可用性、JVM 与系统参数调优未实测。
