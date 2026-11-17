# 06 · API 参考

Base URL：`/api/v1`。响应带 `x-trace-id`；错误体统一为 `{error_code, message, trace_id, details?}`。

## 1. 对话

### `POST /chat`

```json
{
  "message": "lab-node-1 上 nginx 服务启动失败，帮我分析原因",
  "user_id": "u_demo",
  "session_id": "sess_123",
  "stream": false,
  "confirm_action_id": "act_xxx",
  "idempotency_key": "demo-001"
}
```

`session_id`、`confirm_action_id`、`idempotency_key` 均可选。

响应字段：

| 字段 | 说明 |
|:---|:---|
| `answer` | 答案；证据不足时以「【证据不足】…」开头，由代码添加 |
| `session_id` / `trace_id` | 会话与链路标识 |
| `intent` / `complexity` / `strategy` | 运维意图 / 复杂度 / 五路策略 |
| `execution_status` | `completed`、`pending_confirmation`、`refused`、`error` |
| `plan` | Planner 计划：`{"steps":[...], "notes":..., "missing_target":...}` |
| `critic_result` | `{"passed", "issues":[...], "next_action", "gap_query", "checked"}` |
| `critic_round` | Critic 实际修正轮数 |
| `citations[]` | `{citation_id, kind: knowledge\|tool, document_id, title, chunk_id, section, locator, excerpt}` |
| `pending_action` | `{action_id, tool_name, arguments, risk, summary}`；`null` 表示无 |
| `evidence_sufficient` / `evidence_gaps` | 证据是否充分与具体缺口 |
| `tool_trace[]` | `{step_id, name, arguments, success, status, risk, latency_ms, error, fallback_from, executed_tool, failure_kind, idempotent}` |
| `retrieval_detail` | `{rewritten_queries, top_k, knowledge_hits, reranked[], rounds}` |
| `token_usage` / `latency` | 用量与各阶段耗时 |
| `refused` / `error_code` | 拒答标记与稳定错误码 |

确认请求：提交 `confirm_action_id` 时，`ChatRequest` 的 `message` 仍需非空；后端按确认动作执行一次。

### `POST /chat/stream`

SSE 事件负载（`data:` 为 JSON）：

| event | 负载 | 说明 |
|:---|:---|:---|
| `started` | `{"event":"started","trace_id":"..."}` | 链路开始 |
| `node` | `{"event":"node","node":"...", "intent"?, "strategy"?, "tool_trace"?, "evidence_sufficient"?, "evidence_gaps"?}` | 节点级真实进度 |
| `token` | `{"event":"token","text":"..."}` | 完整答案按 48 字符切片推送 |
| `answer` | `{"event":"answer","data":{...ChatResponse}}` | 完整响应 |
| `done` | `{"event":"done","trace_id":"..."}` | 结束 |

## 2. 健康与能力

| 接口 | 说明 |
|:---|:---|
| `GET /health` | 存活探针，返回 `{"status":"ok"}` |
| `GET /ready` | 就绪探针。`database` 为硬依赖；`llm` / `redis` / `vector_store` 为报告项。离线模型显示 `detail=offline_provider`；未配置 Redis 显示 `not_configured` |
| `GET /capabilities` | 实际后端：`database`、`cache`、`vector_store`、`retriever`、`reranker`、`llm`、`degraded`、`ops_backend`、`pending_store`、`hosts` |
| `GET /metrics` | Prometheus 指标（非 `/api/v1` 前缀） |

## 3. 运维只读接口

| 接口 | 说明 |
|:---|:---|
| `GET /ops/hosts` | 白名单主机列表、数量与 `backend` |
| `GET /ops/hosts/{host_id}/overview` | 监控快照：`system`、`resources`、`top_processes`、`disks`、`inode_use_pct`、`services`、`packages`、`error_logs`、`simulated`、`note` |
| `GET /ops/tools` | 只读工具目录：名称、风险、说明、参数 Schema、`enabled`、`read_only`、`requires_confirmation`、`source` |
| `GET /ops/services?host_id=` | systemd / Supervisor 服务清单 |
| `GET /ops/packages?host_id=` | RPM 软件包清单 |
| `GET /ops/knowledge/documents` | 知识清单；只读公开。返回 `document_id`、`title`、`category`、`source_type`、`source_note`、`source_url`、`system`、`applicable_version`、`doc_format`、`updated_at`、`chunk_count` |
| `GET /ops/knowledge/documents/{document_id}` | 文档详情：`found`、`document`（同上）、`chunks[]`（`chunk_id`、`document_id`、`section`、`chunk_index`、`content`） |

`error_logs` 结构：`{service, source, entries[], truncated?, simulated}`。当服务日志不可用，`source=unavailable`、`entries=[]`，不伪造日志。

## 4. 诊断与执行记录

| 接口 | 说明 |
|:---|:---|
| `GET /diagnoses?limit=1..100` | 最近诊断记录；默认 20。返回 `items[]` 与 `count` |
| `GET /diagnoses/{trace_id}` | 单条详情；`found=false` 表示不存在 |

单条记录字段：`trace_id`、`session_id`、`user_id`、`query`、`intent`、`strategy`、`answer`、`citations`、`tool_trace`、`retrieval`、`evidence_sufficient`、`evidence_gaps`、`refused`、`latency`、`created_at`、`execution_status`、`plan`、`critic_result`、`critic_round`。

## 5. 管理与 Skill

| 接口 | 说明 |
|:---|:---|
| `GET /admin/tools` | 管理端工具目录；需 admin（`X-Admin-Token`，开发环境未配置 token 时免鉴权）。前端改用 `/ops/tools` |
| `GET /admin/skills` | 已加载 Skill 摘要；需 admin |

工具条目字段：`name`、`risk`、`description`、`parameters`（JSON Schema）、`enabled`、`read_only`、`requires_confirmation`、`source`。顶层另有 `count`、`write_tools_enabled`。

## 6. 错误码

| 错误码 | HTTP | 触发 |
|:---|:---|:---|
| `INVALID_REQUEST` | 400 / 422 | 参数校验失败、确认卡不匹配 |
| `COMMAND_NOT_ALLOWED` | 400 | 参数含 shell 片段或非法取值 |
| `HOST_NOT_FOUND` | 404 | 主机不在白名单或清单 |
| `PACKAGE_NOT_FOUND` | 404 | 包不存在（RPM 未知包不再返回成功空结果） |
| `SERVICE_NOT_FOUND` | 404 | 服务不存在 |
| `ACTION_ALREADY_CONSUMED` | 409 | 确认卡已消费 |
| `RATE_LIMITED` | 429 | 超过用户请求频率 |
| `CONFIRMATION_STORE_UNAVAILABLE` | 503 | 确认存储不可用；拒绝执行，不降级到进程内字典 |
| `TOOL_TIMEOUT` | 504 | 工具超过 `TOOL_TIMEOUT_SECONDS` |
| `EVIDENCE_INSUFFICIENT` | 200 + 标记 | 证据不足，答案带横幅与缺口 |
| `INTERNAL_ERROR` | 500 | 未预期异常，`details` 在生产环境隐藏 |
