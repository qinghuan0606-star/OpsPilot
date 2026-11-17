# 22 · 数据库设计

> 当前运行数据有两类来源：**SQLite/PostgreSQL 持久化表** 与 **仓库内置 JSON 数据**。

## 1. 数据来源

| 数据 | 来源 | 说明 |
|:---|:---|:---|
| 诊断记录、会话、消息、审计、幂等键 | SQLAlchemy 表 | 每次对话落库；`/diagnoses` 读这里 |
| 主机、服务、日志、RPM、Supervisor、ELK | `app/ops/data/*.json` | 工具读取的主机数据；`hosts`/`packages`/`services` 表存在但当前 API 不以其为准 |
| 知识文档元数据 | `knowledge/_manifest.json` + 启动 ingest | `/ops/knowledge/documents` 读 manifest 与 BM25 语料 |
| 向量 | Qdrant `ops_knowledge` 或进程内 store | 不落 SQL 表 |

`hosts`、`packages`、`services`、`knowledge_documents` 是为关系型后端预留的表；当前数据后端直接读 JSON，API 不查这些表。

## 2. 表结构

### `diagnosis_runs`

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `trace_id` | String(64) PK | 链路 ID |
| `session_id` | String(64) index | 会话 |
| `user_id` | String(64) index | 调用者（请求体传入，非鉴权） |
| `query` | Text | 用户问题 |
| `intent` / `strategy` | String | 意图与五路策略 |
| `answer` | Text | 最终答案 |
| `citations_json` | Text | 引用数组 |
| `tool_trace_json` | Text | 工具轨迹 |
| `retrieval_json` | Text | 检索详情 |
| `evidence_sufficient` | Boolean | 证据是否充分 |
| `evidence_gaps` | Text | `;` 分隔的缺口 |
| `refused` | Boolean | 是否拒答 |
| `latency_json` | Text | 各阶段耗时 |
| `created_at` | DateTime | UTC |

### `diagnosis_traces`

| 列 | 类型 | 说明 |
|:---|:---|:---|
| `trace_id` | String(64) PK | 与 `diagnosis_runs` 一对一 |
| `plan_json` | Text | Planner 计划 |
| `critic_json` | Text | Critic 结果 |
| `critic_round` | Integer | 修正轮数 |
| `execution_status` | String(32) | `completed` / `pending_confirmation` / `refused` / `error` |
| `created_at` | DateTime | UTC |

拆表原因：旧 SQLite/PostgreSQL 只需 additive `CREATE TABLE`，老 `diagnosis_runs` 行仍可读；旧行没有 plan/critic 时返回 `null`。

### 其他表

| 表 | 用途 |
|:---|:---|
| `sessions` | 会话摘要与时间戳 |
| `messages` | 会话消息 |
| `audit_logs` | 工具/确认等审计事件 |
| `idempotency_keys` | `key` + `fingerprint` + `response_json`，防重复提交 |
| `hosts` / `packages` / `services` | 关系型运维平面预留；当前工具数据不依赖 |
| `knowledge_documents` | 知识元数据预留；当前 API 读 manifest |

## 3. 写入链路

```text
ChatService.chat
  → _persist
      → DiagnosisRow（answer/citations/tool_trace/retrieval/evidence/latency）
      → DiagnosisTraceRow（plan/critic/critic_round/execution_status）
      → SessionRow / MessageRow
      → AuditLogRow（如工具执行、确认）
      → IdempotencyRow（如请求带 idempotency_key）
```

`pending_confirmation` 也会落库，`execution_status` 由 trace 表记录；确认后的执行会再写一条诊断记录。

## 4. 迁移

```bash
.venv/bin/alembic upgrade head
```

- `0001_ops`：运维平面表，替换原电商 `orders/returns`。
- `0002_diag_trace`：新增 `diagnosis_traces`，纯 additive。
- SQLite 上 `alembic upgrade head` 通过。
- PostgreSQL 使用同一套迁移。

启动时仍执行 `Base.metadata.create_all`，方便 SQLite 空库直接跑；生产建议只走 Alembic，避免迁移与建表双轨。

## 5. 数据保留与清理

- Redis 确认键：`ops:pending:{action_id}` 带 TTL；消费后写 `ops:pending:used:{action_id}` 带 TTL。

## 6. 一致性约束

- 工具数据是 JSON 数据，同一主机同一服务的状态/日志/配置由 fixture 保证一致。
- 诊断落库与 Redis 确认消费按“先消费、再执行、再落库”的顺序处理。
- 知识 manifest 与 Qdrant 点数量在启动时同步；运行中改 Markdown 后重启生效。
