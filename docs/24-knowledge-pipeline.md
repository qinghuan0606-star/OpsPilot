# 24 · 知识库流水线

> 当前知识库：**29 篇 Markdown、7 个知识域、328 个 BM25 切片**。所有数量以启动后实际索引为准，不以文档标题为准。

## 1. 数据与元数据

```text
knowledge/
  _manifest.json
  linux_*.md / rpm_*.md / systemd_*.md / supervisor_*.md /
  elasticsearch_*.md / logstash_*.md / kibana_*.md /
  os_differences_*.md / ...
```

`_manifest.json` 以文件 stem 为 `doc_id`：

```json
{
  "documents": {
    "os_differences_openeuler_kylin": {
      "title": "openEuler 与麒麟 V10 系统管理差异核对表（公开资料层面）",
      "category": "domestic_os",
      "source_type": "public_summary",
      "source_note": "依据公开文档整理...",
      "source_url": "https://...",
      "system": "openeuler / kylin",
      "applicable_version": "openEuler 24.03 LTS / 麒麟 V10",
      "updated_at": "2026-11-17",
      "doc_format": "runbook"
    }
  }
}
```

字段映射：

| 逻辑字段 | 实际位置 |
|:---|:---|
| `doc_id` | manifest 的 key；同时写入 chunk metadata |
| `title` | manifest `title`，缺省用 stem |
| `category` | manifest `category`，按 `DocumentCategory` 枚举 |
| `source_type` | `self_written` / `public_summary` |
| `source` | `source_note` + `source_url`；chunk metadata 另存文件路径 |
| `system` | `linux_generic` / `openeuler` / `kylin` / `openeuler / kylin` |
| `version` | `applicable_version` |
| `updated_at` | ISO 日期 |

7 个知识域及当前篇数：`log_fault=6`、`rpm_package=5`、`network_disk=4`、`linux_basics=4`、`service_mgmt=4`、`security_perm=3`、`domestic_os=3`。

## 2. 解析

`app/retrieval/unstructured_parser.py::parse_path`：

- 允许 `.md` / `.markdown` / `.txt` 等；无 Unstructured 时只处理 Markdown 类。
- `UNSTRUCTURED_ENABLED=true` 且依赖可用时，调用 `unstructured.partition`；失败则 Markdown 回退。
- Markdown 回退：按 `#` / `##` / `###` 标题切 section，保留 section 标题。
- 空文档返回空列表，日志 `skip_non_markdown_without_unstructured`，不会写入空 chunk。

## 3. 清洗与切片

`app/retrieval/chunking.py`：

- NFKC 归一化、去零宽字符、去控制字符、压缩空白。
- 每个 section 按 **500 字符窗口、60 字符重叠** 切片。
- `chunk_id = <document_id>_<index:02d>`，确定性 ID；文档内容变化但 index 不变时引用仍可定位。
- `chunk_index` 全局递增，保留 `section`、`title`、`category`、`policy_version`。
- `document_id_from_path` 用相对路径 + 8 位 sha1，避免不同 checkout 路径产生不同 ID。

`app/retrieval/cleaning.py::dedupe_chunks`：

- 精确重复：按内容 sha1 去掉后出现的 chunk。
- 近似重复：SimHash 64 位，Hamming ≤ 3 只记录日志，不自动删除；避免误删不同版本的相似条款。
- PII：`redact_chunk_pii` 走 `mask_pii`，对正文与 `table_html` 脱敏。

## 4. Embedding 与 Qdrant 入库

`app/retrieval/ingest.py::KnowledgeIngestor.load`：

```text
list_knowledge_files
  → manifest 绑定
  → parse_path
  → metadata 合并（doc_id/source_type/source_note/source_url/system/applicable_version/updated_at）
  → dedupe_chunks
  → embedder.embed([...])
  → build_records
```

`ingest_knowledge`：

- `QDRANT_URL` 非空 → `QdrantVectorStore(url, "ops_knowledge", 512)`。
- `replace_documents(records)`：按每个 `document_id` 先 `delete` 过滤点，再 `upsert`；文档变短不会留下尾部旧切片。
- Qdrant 失败 → 日志 `qdrant_ingest_failed_using_memory`，降级 `InMemoryVectorStore`，API 仍可启动。
- 重复启动：同一文档的旧点先删后写，不会产生重复向量。

当前集合 `ops_knowledge` green，`points_count=328`，dim 512。

## 5. BM25 与混合检索

- `BM25Retriever(chunks)`：同一批 chunks 建索引，`document_chunk_counts()`、`document_chunks()` 供知识页使用。
- `HybridRetriever.retrieve(query, top_k)`：BM25 与 dense 各自独立失败；两路都失败抛 `RetrievalError`；否则 RRF 融合，按 `RRF_K=60`。
- 可选 `DocumentReranker`：Cross-Encoder 可用时重排；否则 lexical 重排。`/capabilities` 的 `reranker` 字段反映实际。
- `RetrievalCache`：Redis 可用时缓存 query+top_k，TTL 默认 60 秒；Redis 不可用走内存。
- `SelfRAGLoop`：证据不足时按 `MAX_RETRIEVAL_HOPS` 做补充检索；查询改写后的 query 记录在 `retrieval_queries`，避免重复。
- `retrieval_detail`：`rewritten_queries`、`top_k`、`knowledge_hits`、`reranked`、`rounds`，前端工作台展示。

## 6. 检索验证

| 问题 | 结果 |
|:---|:---|
| nginx 启动失败 | 命中《案例：nginx 升级后启动失败》等 5 条知识；工具 2 条 |
| RPM 依赖冲突 | 命中《RPM 安装与卸载：事务、路径冲突与残留》；工具 4 条 |
| Supervisor 频繁退出 | 命中《Supervisor：进程守护、自动重启与日志》等 3 条；工具 4 条 |
| Elasticsearch 大量 ERROR | 命中知识 4 条；ES 工具 3 条，11 条 ERROR |
| Linux 用户无法登录 | 命中《Linux 用户、用户组与登录排查》1 条；无工具 |
| 麒麟 V10 与 openEuler 差异 | 命中差异核对表 |

以上为本地实例上的实际请求结果。

## 7. 已检查的入库问题

| 检查项 | 结果 |
|:---|:---|
| 解析是否成功 | 29 篇全部产生切片；无空文档 |
| 空文档/重复文档 | 0 个空文档；328 个切片内容 sha1 全部唯一 |
| 切片是否丢标题/版本/来源 | chunk 保留 `title`、`section`、`document_id`；metadata 合并 `source_*`、`system`、`applicable_version` |
| 更新文档是否残留旧切片 | `replace_documents` 按 `document_id` 先删后写；同一文档变短不会残留 |
| 重复入库是否重复向量 | 同一文档先删后写；Qdrant `points_count=328` 与 BM25 切片数一致 |
| 检索是否可追溯来源 | citation 含 `document_id`、`title`、`chunk_id`、`section`、`excerpt`；工具 citation 含 `locator` |
