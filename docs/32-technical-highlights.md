# 32 · 五个核心技术难点

> 选标准：既要有设计取舍，也要有真实代码落点，还要能说明“为什么这样做、有什么问题”。以下五点均可在当前仓库找到对应实现。

## 1. 混合检索与重排序

### 为什么需要它

运维知识里有大量“精确 token”：`libGeoIP.so.1`、`systemctl status nginx`、`nginx-mod-http-geoip`、`autorestart=unexpected`。用户提问却常常是自然语言：“nginx 起不来，帮我看看”。只靠 BM25，换一种说法就召回不到；只靠 Dense，命令、错误码、包名这类低频精确词又容易被语义相似的内容挤掉。

### 原来的问题

单路检索的典型失败是：

- BM25 对“启动失败”能召回，但用户说“起不来”时词面不匹配；
- Dense 对语义相近的文档有效，但 `libGeoIP.so.1` 这种错误码可能被泛化成“依赖库问题”；
- 两路结果简单拼接，重复片段多，排序没有统一依据。

### 如何设计

采用“双路召回 + RRF 融合 + 可选重排”：

1. BM25 与 Dense 各自召回 `top_k`，互不阻塞；一路失败仍可用另一路。
2. 用 RRF 按排名融合，`k=60`，不依赖两路分数量纲。
3. 融合后取 `rerank_top_n`，交给 Cross-Encoder 重排；Cross-Encoder 不可用时退化为词面重排。
4. 检索缓存只缓存知识结果，键为 `query + top_k`，不缓存工具结果。

### 具体实现

- `app/retrieval/hybrid.py::HybridRetriever.retrieve`：BM25 与向量分别 `try`，两路都失败才抛 `RetrievalError`；融合后截断、写缓存。
- `app/retrieval/fusion.py::reciprocal_rank_fusion`：按 `1/(k+rank)` 累加。
- `app/retrieval/reranker.py::DocumentReranker`：把融合列表交给 `RerankProvider`，返回带新 `rank`、`score`、`source="rerank"` 的 chunk。
- `app/retrieval/cache.py`：Redis 优先，异常时 `get` 返回 `None`、`set` 静默失败，不阻塞主链路。

## 2. Planner-Executor-Critic 工作流

### 为什么需要它

运维问题不是“检索一次、生成一段”就能解决。用户说“nginx 启动失败”，完整诊断至少需要：查服务状态、查日志、结合 systemd/nginx 知识判断。如果只做 RAG，答案容易停在“请检查日志”；如果只做工具，又缺少知识依据。

### 原来的问题

- 路由直接进入生成，没有显式计划，容易漏工具；
- 工具执行完就生成答案，没有检查“必要工具是否真的执行成功”；
- 失败后没有定向修正，或者一改就无限循环；
- 计划重复时，系统会反复调用同一批工具。

### 如何设计

用 LangGraph 状态机把诊断拆成可检查的步骤：

```text
route → retrieve → assess_evidence → critic
critic → retrieve（补知识） / plan（补工具） / generate（接受）
plan → execute_tools → assess_evidence → critic
generate → faithfulness → memory
```

关键取舍：

- **Critic 在生成之前**：它决定“是否值得再花一轮检索/工具”，而不是事后评价文案。
- **最大修正轮数**：`MAX_CORRECTION_ROUNDS=2`；轮数用尽后把 blocking 降级为 warning，在答案中说明证据不足。
- **计划指纹**：`plan_fingerprint` 对工具名+参数做 sha256；`plan_history` 发现重复计划直接停止重规划。
- **计划上限**：最多 6 步，防止一次规划铺太大。
- **缺参澄清**：服务名或包名缺失时，计划步骤清空并返回澄清，不猜目标。

### 具体实现

- `app/agents/graph.py`：`StateGraph(AgentState)`，条件边 `_route_after_router`、`_after_plan`、`_after_critic`。
- `app/agents/nodes/planner.py`：`Planner.create_plan` 支持 LLM 规划、Skill 计划、离线 heuristic；`_sanitize_plan` 丢弃未注册工具和 Schema 不通过的步骤；`_finalize_plan` 去重、跳过已检索知识、补必要工具。
- `app/agents/nodes/executor.py`：按计划逐步执行，记录 `tool_trace`，处理 fallback、写确认、幂等。
- `app/agents/nodes/critic.py`：确定性检查 `plan_coverage`、`tool_status`、`evidence_kinds`、`evidence_conflict`、`missing_target`、`plan_repeat`；输出 `next_action`。
- `app/agents/state.py`：`plan`、`plan_fingerprint`、`plan_history`、`critic_result`、`critic_round`、`critic_feedback` 等字段。

## 3. 知识证据与工具证据融合

### 为什么需要它

运维答案要能复核。只说“可能是依赖缺失”不够，最好同时给出：

- 知识依据：《nginx 升级后启动失败》里对 `libGeoIP.so.1` 和 ABI 的说明；
- 现场证据：`get_service_status` 返回退出码 1、重启 3 次，`get_service_logs` 返回缺失库和模块不兼容。

如果两类证据各存一份、最终只引用知识，AGENT 路径就会“有工具结果但没引用”；如果只引用工具，又缺少可解释的规则。

### 原来的问题

- Citation 只从检索 chunk 派生，工具结果进不了引用；
- 工具证据和知识证据结构不同，前端无法统一展示；
- 证据够不够靠 Prompt 自觉，模型可能直接下结论；
- 证据冲突没有结构化检查。

### 如何设计

统一 `EvidenceItem`：

```text
evidence_id = kb:<chunk_id> 或 tool:<step_id>:<tool_name>
kind        = knowledge | tool
source      = 文档标题 / 工具名
reference   = chunk_id / locator
title, excerpt, score, rank, metadata
```

- 知识证据由 `retrieval_node` 生成，按 `chunk_id` 去重；第二轮检索保留旧证据的 rank。
- 工具证据由 `executor_node` 生成，读工具返回的 `evidence`；缺省时用白名单字段摘要。
- `generate_answer` 从统一 evidence 派生 Citation，所以离线降级路径也有引用。
- `sufficiency_node` 用代码判断“问题需要哪些工具、是否拿到知识/工具证据”，输出 `evidence_sufficient` 和 `evidence_gaps`。

### 具体实现

- `app/schemas/evidence.py`：`EvidenceItem`、`EvidenceKind`、`knowledge_evidence`、`tool_evidence`。
- `app/agents/nodes/retrieval.py::_merge_knowledge_evidence`：按 `evidence_id` 去重合并。
- `app/agents/nodes/executor.py::evidence_from_result` / `_merge_evidence`：知识 chunk 逐条入证据，工具结果生成一条 tool evidence。
- `app/agents/nodes/sufficiency.py`：`TOOL_REQUIREMENTS`、`required_tools`、`evaluate`、`gap_query`。
- `app/agents/nodes/generate.py`：从 evidence 派生 citation；证据不足时加横幅。

## 4. 工具调用安全、人工确认与幂等

### 为什么需要它

运维工具一旦允许模型拼命令，风险不可控：`rm -rf`、越权主机、参数注入、重复重启。项目选择“能力化工具”，模型只能填结构化参数，不能生成任意 Shell。

### 原来的问题

- 工具 fallback 后仍标 `success=True`，Critic 误以为工具成功；
- 写操作没有一次性约束，用户双击确认可能执行两次；
- 模型可能把“怎么重启”当成“帮我重启”；
- 主机白名单、超时、参数校验散落在各工具里，容易漏。

### 如何设计

四道门：

1. **Schema 门**：每个工具声明 Pydantic `input_model`，`Tool.parse` 校验；日期、路径、关键词拒绝 shell 片段。
2. **权限门**：`ToolRisk` 分 read / write / destructive / external；写工具默认不注册，开启后 `assert_permitted` 要求 `confirmed=True`。
3. **执行门**：`Tool.run` 用 `asyncio.wait_for` 强制执行超时；异常映射为 `ToolTimeoutError` / `ToolExecutionError`，不静默成功。
4. **确认门**：Planner 对显式写请求生成 `pending_action`；`PendingActionStore` 绑定 `session_id + user_id`，Redis Lua 原子消费，只执行一次。

幂等：确认执行时用 `action_id` 或 `idempotency_key` + 参数指纹查 `idempotency_keys`，重复请求复用已有结果。

### 具体实现

- `app/tools/base.py::Tool.run`：`parse → asyncio.wait_for(execute) → 异常映射`。
- `app/tools/permissions.py::assert_permitted`：写风险必须 confirmed。
- `app/agents/nodes/planner.py::_explicit_write_request`：出现“怎么/如何/能不能/为什么”等词时不算写请求；只有“帮我重启/请重启/restart”才生成写步骤。
- `app/agents/nodes/executor.py`：`READ_FALLBACKS` 只允许读工具失败降级到知识检索；`_failure_kind` 区分 timeout / denied / invalid / failed；fallback 结果 `status=FALLBACK`，不标 OK。
- `app/services/pending_store.py::RedisPendingStore`：`ops:pending:{action_id}` TTL 900 秒；Lua 比较 session/user 后 DEL + SET `ops:pending:used:{action_id}`；重复提交返回 409。
- `app/repositories/idempotency.py`：幂等键 + 参数指纹 + 响应。

## 5. Redis 状态管理与异常降级

### 为什么需要它

项目里 Redis 不是“为了用而用”，它承担三类跨请求状态：

- 检索缓存：降低重复 query 的检索成本；
- 用户限流：防止单用户高频请求；
- 待确认动作：保证写操作一次性、可过期、多实例可见。

如果确认状态放在进程内 dict，多 worker/多实例下就会各存一份，用户刷新或负载均衡后确认卡失效，甚至重复执行。

### 原来的问题

- 进程内字典无法跨实例，确认卡不可靠；
- 没有 TTL，过期动作可能一直可执行；
- 用户双击确认，第二次可能报“找不到”，而不是“已消费”；
- Redis 不可用时如果静默降级到内存，会悄悄破坏一次性语义。

### 如何设计

- **缓存**：`query + top_k` 哈希键，TTL 60 秒（配置），Redis 异常时读返回 `None`、写忽略。
- **限流**：`RateLimiter.allow("user:<id>")`，超限抛 `RATE_LIMITED`。
- **确认**：`ops:pending:{action_id}`，TTL 900 秒；值里存 `session_id`、`user_id`、action、创建时间。
- **消费**：Lua 先读、校验 session/user、DEL、SET `used`，原子完成。
- **降级**：`PENDING_STORE_BACKEND=auto` 时，有 Redis 用 Redis，没有则 `DisabledPendingStore`；`memory` 只用于测试。

### 具体实现

- `app/services/pending_store.py::RedisPendingStore.save/consume`：Lua 脚本 `_CONSUME_LUA`，失败映射 503。
- `app/services/pending_store.py::build_pending_store`：`auto` 不做内存兜底。
- `app/retrieval/cache.py::RedisRetrievalCache`：异常吞掉，主链路继续。
- `app/infra/rate_limit.py`：用户级限流。
- `app/services/chat_service.py`：`_resolve_confirmation` 先消费再执行；`_remember_pending` 保存新动作。
