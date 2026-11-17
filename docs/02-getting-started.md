# 02 · 快速开始

> 完整启动、环境变量、Compose 与排障见 [20 · 部署与运维](20-deployment-and-operations.md)。这里只给最短可运行路径。

## 1. 安装

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

默认配置：SQLite、进程内向量库、内置运维工具、离线模式。不需要先建数据库，也不需要 Redis/Qdrant。

## 2. 启动后端

```bash
uvicorn app.asgi:app --reload --port 8000
```

验证：

```bash
curl -s localhost:8000/api/v1/health
curl -s localhost:8000/api/v1/ready
```

期望 `health` 返回 `{"status":"ok"}`；`ready` 的 `database` 为 ready。

## 3. 启动前端

```bash
cd frontend
npm install
npm run build
```

构建完成后，FastAPI 在 `http://127.0.0.1:8000` 提供 `frontend/dist`。开发模式：

```bash
npm run dev     # http://127.0.0.1:5173，/api 代理到 8000
```

## 4. 第一次对话

```bash
curl -s localhost:8000/api/v1/chat \
  -H 'content-type: application/json' \
  -d '{"message":"lab-node-1 上 nginx 服务启动失败，帮我分析原因","user_id":"u_demo"}'
```

预期：`strategy=multi`，`plan` 含 `get_service_status`、`get_service_logs`，`citations` 同时有知识和工具来源。

## 5. 启用 Redis / Qdrant（可选）

```bash
export REDIS_URL=redis://127.0.0.1:6379/0
export QDRANT_URL=http://127.0.0.1:6333
export QDRANT_COLLECTION=ops_knowledge
uvicorn app.asgi:app --port 8000
```

`/api/v1/capabilities` 应显示 `cache=redis`、`vector_store=QdrantVectorStore`、`pending_store=RedisPendingStore`。

## 6. 常见问题

- 启动报数据库错误：确认 `data/local/` 可写，或重设 `DATABASE_URL`。
- 检索只有 BM25：检查 `LOCAL_EMBEDDING_ENABLED` 与模型权重；hash 回退是预期降级。
- 重启请求不返回确认卡：默认 `OPS_ENABLE_WRITE_TOOLS=false`，写工具未注册。
- 前端 404：先 `npm run build`，或使用开发模式的 5173 端口。
