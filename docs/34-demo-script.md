# 34 · 项目演示讲稿（nginx 启动失败，3～5 分钟）

> 以下讲稿按 4 分 30 秒设计，可按现场节奏压缩到 3 分钟。

## 0:00—0:20 开场

大家好，我演示的是 OpsPilot，一个面向国产操作系统的智能运维诊断平台。

它要解决的不是“大模型会不会讲 systemd”，而是“这台机器上的 nginx 为什么起不来”。所以我会重点展示两条线：一条是知识检索，一条是工具取证，最后它们怎么合成一个可追溯的答案。

## 0:20—0:40 提出问题

我在工作台输入：

> lab-node-1 上 nginx 服务启动失败，帮我分析原因。

这个问题的关键信息有三个：主机 `lab-node-1`、服务 `nginx`、现象“启动失败”。系统要做的不是直接生成一段通用建议，而是先判断这是不是一个需要现场取证的诊断问题。

## 0:40—1:10 Agent 分析与路由

请求进来后，先过安全护栏，再做意图识别。这里识别为 `fault_diagnosis`，复杂度路由到 `multi`，也就是多跳诊断，不是普通问答。

工作台右侧会看到节点链：

```text
apply_guardrail → classify_intent → route_complexity → retrieve_docs
→ assess_evidence → critic_diagnosis → plan_tasks → execute_tools
→ assess_evidence → critic_diagnosis → generate_answer
→ check_faithfulness → compact_memory
```

注意，`multi` 也会先检索知识，再决定要不要调工具。这是刻意的：如果只拿现场日志，答案会缺少“为什么”的解释。

## 1:10—1:50 RAG 检索

检索层做两件事：BM25 召回和向量召回，然后用 RRF 融合，最后重排。

BM25 负责命中“nginx 启动失败”“libGeoIP”这类精确词；向量召回负责“起不来”“启动不了”这种语义表达。RRF 按排名融合，不需要把两种分数硬归一化。

这次命中 5 条知识来源，包括 nginx 升级后启动失败的案例、systemd 服务排查、依赖库加载失败等。每条引用都带 `document_id`、`chunk_id`、章节和来源，不是一句“根据资料”。

## 1:50—2:40 Planner 与 Executor

接下来 Planner 生成计划。这个场景是两步：

1. `get_service_status`：查 nginx 的运行状态、退出码、重启次数、是否 enabled；
2. `get_service_logs`：查 journal 日志尾部，定位启动失败的直接原因。

Executor 逐步执行。工具不是让模型拼 Shell，而是结构化能力：参数必须过 Pydantic Schema，主机必须在白名单，单次调用有超时。

执行结果进入统一 `tool_trace` 和 `Evidence`。这次状态返回：`failed`、退出码 1、重启 3 次；日志里能看到 `libGeoIP.so.1` 缺失，以及旧模块和当前 nginx 的 ABI 不兼容。

这里可以强调一句：工具失败或 fallback 不会被标成成功；读工具失败才会按白名单降级到知识检索，而且状态是 `fallback`，不是 `ok`。

## 2:40—3:20 Critic 检查

工具执行完，不是马上生成答案，而是先过 Critic。

Critic 检查六件事：计划有没有覆盖必要工具、工具是否真的成功、有没有知识和工具两类证据、结构化证据是否冲突、目标服务是否和用户说的一致、计划是否重复。

这个例子六项都通过，所以进入答案生成。如果是 RPM 场景，Critic 可能通过但带 `evidence_conflict` warning：软件包显示已安装，依赖检查却存在缺失。这不是 bug，而是升级残留的典型状态，需要把冲突呈现给用户。

## 3:20—4:10 最终答案与证据

最终答案会同时引用知识和工具：

- 知识侧解释：nginx 动态模块加载依赖 `libGeoIP.so.1`，模块与主程序版本不匹配会报 ABI 错误；
- 工具侧证明：这台机器退出码 1、重启 3 次，日志确实缺少 `libGeoIP.so.1`，并且模块版本不兼容。

工作台会展示 Planner 两步、工具调用状态、Critic 通过、5 条知识引用和 2 条工具引用。用户不需要相信一句结论，可以顺着引用回到原文和工具 locator。

## 4:10—4:40 收尾

这个演示完整展示了“用户提问 → 意图识别 → RAG 检索 → Planner 拆解 → Executor 调用工具 → Critic 检查 → 带证据的最终答案”的闭环。

从工程角度看，它把知识检索、工具协议、证据模型和人工确认串成了一条可追溯的链路；后续可以继续扩展采集适配、检索评测和容器化部署能力。

## 演示操作卡（可选）

```bash
# 1. 健康检查
curl -s localhost:8000/api/v1/health
curl -s localhost:8000/api/v1/ready
curl -s localhost:8000/api/v1/capabilities

# 2. 主场景
curl -s localhost:8000/api/v1/chat \
  -H 'content-type: application/json' \
  -d '{"message":"lab-node-1 上 nginx 服务启动失败，帮我分析原因","user_id":"u_demo"}'

# 3. 浏览器
# 打开 http://127.0.0.1:8000/workbench，提交同一问题
```

讲解时重点看四个字段：`strategy`、`plan.steps`、`tool_trace`、`citations`。如果时间只够 3 分钟，可以跳过 RAG 细节，只讲“知识 5 条 + 工具 2 条 + Critic 通过”。
