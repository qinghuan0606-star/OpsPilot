# 07 · 配置参考

> 运行时配置统一在 `app/config/settings.py` 的 `Settings`；密钥字段用 `SecretStr`；`.env` 只放在本地，禁止提交。

## 1. 加载顺序

1. 进程环境变量（最高）。
2. 项目根 `.env`（`pydantic-settings` 读取）。
3. `Settings` 字段默认值。

`APP_ENV=testing` 时默认跳过本地 embedding / Cross-Encoder / Unstructured，除非对应 `*_FORCE=true`；测试用 `tests/conftest.py` 覆盖。

## 2. 应用与日志

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `APP_ENV` | `development` | `production` 时 Admin 强制 `X-Admin-Token` |
| `APP_NAME` | `opspilot` | 日志与指标名 |
| `LOG_LEVEL` | `DEBUG` | 生产建议 `INFO` |
| `API_V1_PREFIX` | `/api/v1` | API 前缀 |
| `KNOWLEDGE_DIR` | `knowledge` | 启动时全量 ingest |
| `ADMIN_API_TOKEN` | 空 | 生产必填；开发为空时 Admin 放行 |

## 3. 模型

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `DEEPSEEK_API_KEY` | 空 | 空则使用离线模式 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_TIMEOUT_SECONDS` | `30` | 单次调用超时 |
| `LLM_MAX_RETRIES` | `3` | 重试次数 |
| `EMBEDDING_MODEL` | `bge-small-zh-v1.5` | 远端 embedding 模型名 |
| `EMBEDDING_DIM` | `512` | 必须与 Qdrant 集合维度一致 |
| `LOCAL_EMBEDDING_ENABLED` | `true` | 是否加载本地 BGE |
| `LOCAL_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 本地模型 |
| `LOCAL_EMBEDDING_DEVICE` | 空 | `cpu` / `cuda` |
| `LOCAL_EMBEDDING_FORCE` | `false` | testing 下强制加载 |
| `CROSS_ENCODER_ENABLED` | `true` | 是否加载 Cross-Encoder |
| `CROSS_ENCODER_MODEL` | `BAAI/bge-reranker-base` | 重排模型 |
| `CROSS_ENCODER_DEVICE` | 空 | 设备 |
| `CROSS_ENCODER_MAX_LENGTH` | `512` | 截断长度 |
| `CROSS_ENCODER_FORCE` | `false` | testing 下强制加载 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | Hugging Face 镜像 |

远端与本地 embedding 同时配置时，远端优先。

## 4. 存储

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/local/app.db` | SQLite 或 PostgreSQL |
| `REDIS_URL` | 空 | 空则缓存走内存 |
| `QDRANT_URL` | 空 | 空则向量走内存 |
| `QDRANT_COLLECTION` | `ops_knowledge` | 集合名 |
| `POSTGRES_PASSWORD` | 空 | Compose single/multi 必填，只写本地 `.env` |
| `DB_POOL_SIZE` | `5` | SQLAlchemy 连接池 |
| `DB_MAX_OVERFLOW` | `10` | 连接池溢出 |
| `DB_POOL_TIMEOUT` | `30` | 获取连接超时 |

## 5. 检索与 Agent

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `RETRIEVAL_TOP_K_SIMPLE` | `3` | SINGLE 检索数 |
| `RETRIEVAL_TOP_K_COMPLEX` | `8` | MULTI/AGENT 检索数 |
| `RRF_K` | `60` | RRF 常数 |
| `RERANK_TOP_N` | `5` | 重排保留数 |
| `MAX_RETRIEVAL_HOPS` | `3` | 检索跳数上限 |
| `MAX_EVIDENCE_HOPS` | `2` | 工具后补充检索上限 |
| `MAX_AGENT_STEPS` | `8` | 图步数上限 |
| `MAX_TOOL_CALLS` | `6` | 单计划工具调用上限 |
| `MAX_CORRECTION_ROUNDS` | `2` | Critic 修正轮数 |
| `TOKEN_BUDGET` | `128000` | 上下文预算 |
| `COMPRESS_SOFT_RATIO` | `0.50` | 软压缩阈值 |
| `COMPRESS_HARD_RATIO` | `0.70` | 硬压缩阈值 |
| `AUTO_COMPACT_RATIO` | `0.85` | 自动压缩阈值 |

## 6. 运维平面

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `OPS_TOOL_BACKEND` | `mock` | 数据后端选择 |
| `OPS_FIXTURES_DIR` | `app/ops/data` | 主机数据目录 |
| `OPS_DEFAULT_HOST` | `lab-node-1` | 未指定主机时的默认 |
| `OPS_ALLOWED_HOSTS` | `lab-node-1,lab-node-2` | 主机白名单，越权直接拒绝 |
| `OPS_ENABLE_WRITE_TOOLS` | `false` | 开启后才注册 `restart_service` |
| `TOOL_TIMEOUT_SECONDS` | `8` | `Tool.run` 的 `asyncio.wait_for` 预算 |
| `PENDING_STORE_BACKEND` | `auto` | `auto`：有 Redis 用 Redis，否则 disabled；`memory` 仅测试 |
| `PENDING_ACTION_TTL_SECONDS` | `900` | 确认卡 TTL |
| `RATE_LIMIT_PER_MINUTE` | `60` | 用户请求限流 |
| `RETRIEVAL_CACHE_TTL_SECONDS` | `60` | 检索缓存 TTL |
| `MCP_ENABLED` | `true` | 是否加载 MCP 代理工具 |
| `MCP_REMOTE_URL` | 空 | 远端 MCP 地址 |

## 7. 能力开关与安全

- `LOCAL_EMBEDDING_ENABLED=false`：dense 检索使用 hash embedding；BM25 仍工作。
- `CROSS_ENCODER_ENABLED=false`：使用 lexical 重排。
- `UNSTRUCTURED_ENABLED=false`：Markdown 走标题切分；非 Markdown 文件跳过。
- `OPS_ENABLE_WRITE_TOOLS=false`：`restart_service` 不注册，前端不会出现确认卡。
- `PENDING_STORE_BACKEND=auto` 且没有 Redis：确认存储 disabled，确认请求返回 503，不执行。
- `APP_ENV=production` 且 `ADMIN_API_TOKEN` 为空：Admin API 直接拒绝。

## 8. 配置检查

```bash
curl -s localhost:8000/api/v1/capabilities
```

重点核对：`cache`、`vector_store`、`llm`、`reranker`、`pending_store`、`ops_backend`、`degraded`。
