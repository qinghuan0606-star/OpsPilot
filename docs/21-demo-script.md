# 21 · 演示脚本

> 演示目标：一条问题如何经过“意图 → 检索 → 计划 → 工具 → Critic → 答案与引用”。

## 0. 前置检查

```bash
curl -s localhost:8000/api/v1/health
curl -s localhost:8000/api/v1/ready
curl -s localhost:8000/api/v1/capabilities
```

本地实际验证使用 8020 端口（Redis + Qdrant + SQLite），结果为：

```json
{"status":"ok"}
{"ready":true,"dependencies":[
  {"name":"database","ready":true,"detail":""},
  {"name":"llm","ready":true,"detail":"offline_provider"},
  {"name":"redis","ready":true,"detail":""},
  {"name":"vector_store","ready":true,"detail":"QdrantVectorStore"}]}
```

`capabilities`：`database=sqlite`、`cache=redis`、`vector_store=QdrantVectorStore`、`retriever=bm25`、`reranker=lexical`、`pending_store=RedisPendingStore`、`hosts=2`。

## 1. nginx 启动失败（MULTI）

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "message":"lab-node-1 上 nginx 服务启动失败，帮我分析原因",
  "user_id":"u_demo"
}'
```

实际结果：

- `intent=fault_diagnosis`，`strategy=multi`，`execution_status=completed`
- Planner：`get_service_status` → `get_service_logs`
- Critic：通过，6 项检查全过
- 证据：5 条知识来源 + 2 条工具来源
- 答案：退出码 1、重启 3 次；`libGeoIP.so.1` 缺失；模块 ABI 不兼容

演示讲解点：知识证据解释“为什么”，工具证据解释“这台机器发生了什么”，引用同时出现。

## 2. RPM 依赖冲突（AGENT）

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "message":"lab-node-1 上 nginx RPM 包升级时出现依赖冲突，帮我分析原因",
  "user_id":"u_demo"
}'
```

实际结果：

- `intent=package_rpm`，`strategy=agent`
- Planner：`get_rpm_info` → `check_rpm_dependencies` → `get_service_status` → `get_service_logs`
- 四步均成功；Critic 通过，但带 `evidence_conflict` warning：软件包已安装，依赖检查却存在缺失/冲突
- 答案列出缺失依赖 `nginx-mod-http-geoip = 1.26.1-1.oe2403`、`GeoIP (libGeoIP.so.1)`，并指出版本锁定冲突

演示讲解点：`evidence_conflict` 不是失败，而是提醒“已安装”和“依赖不满足”可以同时为真；这正是升级残留的典型状态。

## 3. Supervisor 频繁退出（AGENT）

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "message":"lab-node-1 上 app-worker 被 Supervisor 反复重启，帮我分析原因",
  "user_id":"u_demo"
}'
```

实际结果：

- `intent=service_ops`，`strategy=agent`
- Planner：`get_service_status` → `get_service_logs` → `list_supervisor_programs` → `get_supervisor_program_config`
- 四步均成功；Critic 通过
- 答案：`app-worker` 状态 failed、退出码 2、重启 5 次；日志 `Exited too quickly`、`FATAL`；配置 `autorestart=unexpected`、`startsecs=2`、`startretries=5`

演示讲解点：程序自身在 `startsecs` 内提前退出，Supervisor 按策略重试到上限后进入 FATAL。要区分“应用启动即崩”和“重启策略配置不当”。

## 4. Elasticsearch 大量 ERROR（AGENT）

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "message":"lab-node-1 最近 Elasticsearch 应用日志出现大量 ERROR，帮我分析原因",
  "user_id":"u_demo"
}'
```

实际结果：

- `intent=log_analysis`，`strategy=agent`
- Planner：`search_elasticsearch_logs` → `aggregate_error_logs` → `get_logstash_pipeline_status`
- 三步均成功；Critic 通过
- ES 命中 11 条 ERROR；聚合 `DatabaseConnectionError=4`、`NginxModuleLoadError=2`、`SupervisorStartFailure=2`；涉及服务 `app-api`、`app-worker`、`nginx`
- Logstash 返回 3 条 Pipeline 状态

演示讲解点：这里的证据来自 Elasticsearch 日志数据，不是本地 journal；如果用户明确要查 ES，Planner 不会静默退化成 `get_service_logs`。

## 5. 国产 OS 差异（MULTI）

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "message":"麒麟 V10 上 nginx 服务启动失败，和 openEuler 有什么差异？",
  "user_id":"u_demo"
}'
```

实际结果：

- `intent=fault_diagnosis`，`strategy=multi`
- 工具：`get_service_status`、`get_service_logs`
- 引用包含《openEuler 与麒麟 V10 系统管理差异核对表》

## 6. Linux 用户与权限（SINGLE）

```bash
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "message":"Linux 中如何排查用户无法登录的问题？",
  "user_id":"u_demo"
}'
```

实际结果：

- `intent=fault_diagnosis`，`strategy=single`
- 无工具调用；引用《Linux 用户、用户组与登录排查》
- 内置回答模式返回证据节选（`usermod` 占用、附加组覆盖、目录权限、`namei -l` 等）

演示讲解点：纯知识问题不强行调工具；回答按证据节选组织。

## 7. 人工确认：重启 nginx

```bash
# 第一次：只返回待确认动作，不执行
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "message":"重启 lab-node-1 的 nginx",
  "user_id":"u_demo"
}'
```

实际结果：

- `execution_status=pending_confirmation`
- `pending_action`：`restart_service`，`risk=destructive`，摘要写明动作风险与执行范围
- 记下 `action_id`

```bash
# 第二次：确认执行；把 act_xxx 替换为实际 action_id
curl -s localhost:8000/api/v1/chat -H 'content-type: application/json' -d '{
  "message":"确认执行",
  "user_id":"u_demo",
  "confirm_action_id":"act_xxx"
}'
```

实际结果：200 / `completed`，执行一次 `restart_service`。再次提交同一个 `action_id` 返回 HTTP 409 `ACTION_ALREADY_CONSUMED`。Redis 中存在 `ops:pending:used:<action_id>`，证明原子消费路径真实跑过。

## 8. 浏览器演示

打开 `http://127.0.0.1:8000/workbench`，提交第 1 条 nginx 问题。右侧节点链实际显示：

```text
apply_guardrail → classify_intent → route_complexity → retrieve_docs
→ assess_evidence → critic_diagnosis → plan_tasks → execute_tools
→ assess_evidence → critic_diagnosis → generate_answer
→ check_faithfulness → compact_memory
```

面板显示策略 `multi`、证据充分、命中 5、Planner 2 步、Critic 通过、工具调用、状态 `completed`。截图见 `docs/assets/frontend-workbench.png`。
