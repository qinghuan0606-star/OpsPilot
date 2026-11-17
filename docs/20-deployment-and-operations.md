# 20 · 部署与运维

## 1. 三种部署拓扑

| 文件 | 组件 | 适用 | 数据持久化 |
|:---|:---|:---|:---|
| `docker-compose.yml` | 单 API + SQLite + 进程内检索 | 本地演示 | `opspilot-data:/app/data` |
| `docker-compose.single.yml` | PostgreSQL 16 + Redis 7 + API | 单机试用 | `postgres-data` |
| `docker-compose.multi.yml` | PostgreSQL 16 + Redis 7 + Qdrant 1.12.5 + 双 API + Nginx 1.27 | 多实例演示 | `postgres-data`、`qdrant-data` |

默认拓扑**不启动** Redis 和 Qdrant，确认存储显式为 `disabled`，因此重启类写操作不会产生确认卡。这是默认演示的安全选择，不是能力缺失。

## 2. 构建与启动

```bash
# 默认演示
docker compose up --build -d

# 单机
export POSTGRES_PASSWORD='change-this-password'
docker compose -f docker-compose.single.yml up --build -d

# 多实例
export POSTGRES_PASSWORD='change-this-password'
docker compose -f docker-compose.multi.yml up --build -d
```

镜像阶段：

1. `node:24-alpine` 执行 `npm ci && npm run build`。
2. `python:3.11-slim` 安装项目，复制 `app/`、`knowledge/`、`alembic/`、`alembic.ini`、`frontend/dist`。
3. 非 root `appuser` 启动 `uvicorn app.asgi:app --host 0.0.0.0 --port 8000`。
4. 容器健康检查请求 `/api/v1/health`，`start_period=30s`。

构建参数：

```bash
docker build --build-arg INSTALL_RERANK=true -t opspilot:rerank .
```

`INSTALL_RERANK=true` 会安装 `sentence-transformers` 与 `modelscope`，镜像明显变大；默认 `false`，本地 embedding 与 Cross-Encoder 关闭。

## 3. 环境变量

完整模板见 `.env.example`。关键项：

| 变量 | 默认 | 说明 |
|:---|:---|:---|
| `APP_ENV` | `development` | 生产为 `production`，Admin 强制 token |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/local/app.db` | 单机/多实例覆盖为 PostgreSQL |
| `REDIS_URL` | 空 | 为空时缓存走内存，确认存储按 `PENDING_STORE_BACKEND` |
| `QDRANT_URL` | 空 | 为空时向量库走内存 |
| `QDRANT_COLLECTION` | `ops_knowledge` | 集合名 |
| `PENDING_STORE_BACKEND` | `auto` | `auto`：有 Redis 用 Redis，否则 disabled；`memory` 仅测试 |
| `OPS_TOOL_BACKEND` | `mock` | 数据后端选择 |
| `OPS_ALLOWED_HOSTS` | `lab-node-1,lab-node-2` | 主机白名单 |
| `OPS_ENABLE_WRITE_TOOLS` | `false` | 开启后才注册 `restart_service` |
| `DEEPSEEK_API_KEY` | 空 | 空则使用离线模式 |
| `LOCAL_EMBEDDING_ENABLED` | `true`（本地）/ `false`（Compose） | 容器默认关闭，避免启动时下载权重；需要语义向量时显式开启并预置权重 |
| `CROSS_ENCODER_ENABLED` | `true`（本地）/ `false`（Compose） | 容器默认关闭；需要重排时显式开启 |
| `MAX_CORRECTION_ROUNDS` | `2` | Critic 定向修正上限 |
| `POSTGRES_PASSWORD` | 空 | 单机/多实例必填；只写本地 `.env` |

密钥只放在本地 `.env` 或环境变量，不写入代码、镜像层或 Git。

## 4. 启动顺序与健康检查

```text
PostgreSQL / Redis / Qdrant
  → API（启动时 ingest 知识、建 BM25、连接 Qdrant）
    → Nginx（多实例）
      → 浏览器
```

| 接口 | 期望 |
|:---|:---|
| `GET /api/v1/health` | `{"status":"ok"}` |
| `GET /api/v1/ready` | `database` 必须 ready；LLM/Redis/Qdrant 是报告项 |
| `GET /api/v1/capabilities` | `cache`、`vector_store`、`pending_store` 与部署拓扑一致 |

`/ready` 在离线模式下会显示 `llm.detail=offline_provider`，反映当前运行配置。

## 5. 数据持久化与迁移

```bash
.venv/bin/alembic upgrade head
```

- SQLite 路径：`./data/local/app.db`，诊断记录与会话在其中。
- Compose 把 `/app/data` 挂到命名卷；`docker compose down` 不删卷，`down -v` 才会删数据。
- PostgreSQL 通过同一套 Alembic 迁移管理。
- 启动时仍有 `Base.metadata.create_all` 兼容建表；生产建议只跑迁移。

## 6. 实际验证记录

验证时间：2026-11-17。环境：Linux 云主机。

| 项 | 结果 | 类型 |
|:---|:---|:---|
| Redis 7.2.5 | 源码编译启动，`redis-cli ping` 返回 `PONG`；API 使用真实 Redis 缓存与确认存储 | 真实执行 |
| Qdrant 1.12.5 | 启动 `6333/6334`；集合 `ops_knowledge` green，`points_count=328`，dim 512 | 真实执行 |
| FastAPI 8020 | Redis + Qdrant + SQLite + 内置工具；`/health` ok；`/ready` 四项 ready | 真实执行 |
| FastAPI 8021 | 无 Redis/Qdrant，`cache=memory`、`vector_store=memory`、`pending_store=DisabledPendingStore`；`/ready` 正常 | 真实执行 |
| 知识检索 | 29 篇 / 7 域 / 328 切片；nginx、RPM、Supervisor、ELK 场景均命中知识并引用 | 本地执行 |
| Agent | nginx 场景 `multi`，Planner 2 步，Critic 通过，5 条知识来源；RPM/Supervisor/ELK 走 `agent` | 本地执行 |
| 人工确认 | 重启请求返回 `pending_confirmation`；确认后执行一次；重复提交 409；Redis 有 `used` 键 | 真实执行 |
| 六页面 | 浏览器逐页加载，工作台提交 nginx 问题并显示完整节点链 | 本地执行 |

## 7. 常见排障

| 现象 | 检查 |
|:---|:---|
| 启动即失败 | `DATABASE_URL` 是否可写；`knowledge/` 是否存在；端口是否被占 |
| `/ready` database 失败 | SQLite 目录权限、PostgreSQL 连接串、迁移是否执行 |
| 检索只有 BM25 | 检查 `LOCAL_EMBEDDING_ENABLED`、模型权重、`QDRANT_URL`；hash fallback 是预期降级 |
| `/capabilities` 显示 `degraded=true` | 看 `llm`、`cache`、`vector_store` 哪个是离线或内存 |
| 重启请求直接执行 | 检查 `OPS_ENABLE_WRITE_TOOLS` 与 `PENDING_STORE_BACKEND`；默认演示应返回 `pending_confirmation` 或明确拒绝 |
| SSE 看起来一次性出现 | 答案完整生成后按 48 字符切片下发 |
| 多实例 SSE 被缓冲 | 检查 `deploy/nginx.multi.conf` 的 `proxy_buffering off` / `proxy_cache off` |

## 8. 安全控制

- 工具通过能力接口执行，`restart_service` 必须人工确认。
- Redis 不可用时确认存储返回 503，不降级到进程内 dict。
- 生产环境通过网关绑定用户身份，并配置 `ADMIN_API_TOKEN`。
- 前端工具页读 `/api/v1/ops/tools`（只读目录）；知识页读 `/api/v1/ops/knowledge/*`。这些公开只读接口不返回密钥，也不执行工具；`/api/v1/admin/tools` 仍要求 Admin Token。
