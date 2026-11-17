# 03 · 系统架构

> 本文只描述当前代码里真实存在的结构。运行时能力以 `/api/v1/capabilities` 为准，工具清单以 `/api/v1/ops/tools` 为准；`/api/v1/admin/tools` 保留给管理端。

## 1. 请求链路

```text
HTTP /api/v1/chat, /api/v1/chat/stream
   └─ ChatService.chat / stream
        ├─ 幂等键、限流、trace_id、审计
        ├─ 确认解析（confirm_action_id → PendingActionStore.consume）
        ├─ LangGraph.ainvoke / astream
        └─ 落库 diagnosis_runs + diagnosis_traces
           → ChatResponse（answer / citations / plan / critic_result / tool_trace / evidence_*）
```

`ChatService` 不直接检索、不直接调工具；请求级关注点与 Agent 执行分离。

## 2. LangGraph 拓扑

```text
START → apply_guardrail
          ├─ refused → refuse_answer → compact_memory → END
          └─ → classify_intent → route_complexity
                                 ├─ DIRECT → generate_answer
                                 ├─ REFUSE → refuse_answer
                                 ├─ SINGLE/MULTI/AGENT → retrieve_docs
                                 └─ confirmed_action → plan_tasks

retrieve_docs → assess_evidence → critic_diagnosis
critic_diagnosis
   ├─ next_action=retrieve → retrieve_docs
   ├─ next_action=plan     → plan_tasks
   └─ accept / clarify     → generate_answer

plan_tasks
   ├─ 缺少必要参数 / pending_action → generate_answer
   └─ execute_tools → assess_evidence → critic_diagnosis

generate_answer → check_faithfulness → compact_memory → END
refuse_answer → compact_memory → END
```

当前节点：

| 节点 | 文件 | 职责 |
|:---|:---|:---|
| `apply_guardrail` | `app/agents/nodes/guardrail.py` | 危险请求拦截，零检索零工具 |
| `classify_intent` | `app/agents/nodes/intent.py` | 运维意图识别 |
| `route_complexity` | `app/agents/nodes/router.py` | 五路策略 |
| `retrieve_docs` | `app/agents/nodes/retrieval.py` | 查询改写、BM25+向量、RRF、重排、证据生成 |
| `assess_evidence` | `app/agents/nodes/sufficiency.py` | 确定性证据充分性判定 |
| `critic_diagnosis` | `app/agents/nodes/critic.py` | 生成前检查计划覆盖、工具状态、证据类型、冲突、重复 |
| `plan_tasks` | `app/agents/nodes/planner.py` | 生成工具计划、缺参澄清、写操作待确认 |
| `execute_tools` | `app/agents/nodes/executor.py` | 白名单、超时、降级、幂等、tool_trace |
| `generate_answer` | `app/agents/nodes/generate.py` | 证据派生引用、证据不足横幅 |
| `check_faithfulness` | `app/agents/nodes/faithfulness.py` | 生成后忠实度检查 |
| `compact_memory` | `app/agents/nodes/memory.py` | 上下文预算与压缩 |

## 3. 证据与引用

统一证据模型在 `app/schemas/evidence.py`：

```python
EvidenceItem(
    evidence_id,        # kb:<chunk_id> 或 tool:<step_id>:<tool_name>
    kind,               # knowledge | tool
    source, reference,  # reference：知识为 chunk_id，工具为 locator（如 systemctl:nginx@lab-node-1）
    title, excerpt, score, rank, metadata,
)
```

- 知识证据由 `retrieval_node` 生成，去重合并；第二轮检索保留旧证据。
- 工具证据由 `executor_node` 生成，读工具返回的 `evidence`，缺省时用白名单字段摘要。
- `generate_answer` 从证据派生 `Citation`，所以 AGENT 路径、离线降级路径都有引用。
- `evidence_sufficient` / `evidence_gaps` 由 `sufficiency_node` 计算；答案里的「【证据不足】」横幅由代码添加，不依赖 Prompt 自觉。

## 4. 工具平面

当前默认注册 16 个工具；`OPS_ENABLE_WRITE_TOOLS=true` 后为 17 个。

```text
ToolRegistry
  ├─ 12 个只读运维工具：
  │   get_system_info / get_cpu_memory / get_disk_usage /
  │   get_service_status / get_service_logs /
  │   get_rpm_info / check_rpm_dependencies /
  │   list_supervisor_programs / get_supervisor_program_config /
  │   search_elasticsearch_logs / aggregate_error_logs /
  │   get_logstash_pipeline_status
  ├─ search_knowledge / escalate_to_human
  ├─ MCP 代理：mcp_change_window / mcp_oncall_roster（组织策略封装）
  └─ restart_service（仅 OPS_ENABLE_WRITE_TOOLS=true 时注册，必须人工确认）
```

`OpsBackend` 是能力化接口（`system_info(...)`、`service_status(...)`），没有 `run(command)`；模型不能生成任意 Shell。后端通过统一能力接口读取 `app/ops/data/*.json` 中的主机数据。

`Tool.run()` 统一做：参数 Schema 校验 → 主机白名单 → `asyncio.wait_for` 超时 → 异常映射 → 结构化 `ToolResult`。`executor_node` 负责 READ 工具失败降级到 `search_knowledge`、写工具确认、幂等复用和 `tool_trace`。

## 5. 确认流程

```text
用户显式请求重启 → planner 生成单步 restart_service 计划
   → 返回 pending_action(action_id, arguments, risk=destructive, summary)
   → 用户提交 confirm_action_id
   → PendingActionStore.consume(action_id, session_id, user_id)
        · Redis：Lua 原子比较 session/user → DEL key → SET used EX ttl
        · 不匹配 → InvalidRequestError；已消费 → ActionAlreadyConsumedError(409)
        · 存储不可用 → ConfirmationStoreUnavailableError(503)，不执行
   → execute_tools 执行一次，随后幂等键防止重复提交
```

`pending_action` 键为 `ops:pending:{action_id}`，TTL 默认 900 秒，绑定 `session_id + user_id`。确认、消费和 409 重复提交均已验证。

## 6. 降级策略

| 依赖 | 缺失时的行为 |
|:---|:---|
| LLM Key | 内置离线回答：意图走规则、答案走证据节选 |
| Embedding 权重 | hash embedding（维度不变，检索质量下降） |
| Cross-Encoder 权重 | 词面重排 |
| Qdrant | 内存向量库 |
| Redis | 检索缓存降级内存；确认存储直接 Disabled（503），不落到进程内 dict |
| Unstructured | Markdown 标题切分 |

`/ready` 把 database 作为硬依赖，LLM/Redis/Qdrant 只报告；`/capabilities` 报告实际后端与 `degraded` 标记。

## 7. 前端

六页由 React Router 承载：`/workbench`、`/knowledge`、`/tools`、`/diagnoses`、`/traces`、`/monitoring`。工作台右侧面板消费 SSE 的 `node` 事件以及 `answer` 事件里的 `tool_trace` / `evidence_gaps` / `retrieval_detail`。

SSE 在答案完整生成后按 48 字符切片下发 `token` 事件，前端逐段呈现答案内容。

## 8. 部署形态

| 形态 | 组件 | 检索/确认 | 数据卷 |
|:---|:---|:---|:---|
| 默认演示 `docker-compose.yml` | 单 API | SQLite + 内存向量 + 确认存储 disabled | `opspilot-data` |
| 单机 `docker-compose.single.yml` | PostgreSQL + Redis + API | PostgreSQL + Redis + 内存向量 | `postgres-data` |
| 多实例 `docker-compose.multi.yml` | PostgreSQL + Redis + Qdrant + 双 API + Nginx | 全部真实依赖 | `postgres-data`、`qdrant-data` |

Nginx 配置见 `deploy/nginx.multi.conf`，已关闭代理缓冲以支持 SSE。
