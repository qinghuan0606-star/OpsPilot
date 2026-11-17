# 31 · 简历项目经历

> 以下内容可直接粘贴到简历。项目时间：2026.09—2026.11。

## 简历条目

**OpsPilot｜基于 RAG 与 Agent 的国产操作系统智能运维平台**

**项目时间：** 2026.09—2026.11

**技术栈：** Python、FastAPI、Pydantic、SQLAlchemy、Alembic、LangGraph、BM25、BGE-small、RRF、Cross-Encoder、Qdrant、Redis、SQLite/PostgreSQL、React 19、TypeScript、Vite、Docker Compose、Nginx

**项目简介：** 面向 Linux、openEuler 与麒麟 V10 的智能运维诊断平台。将运维知识检索、主机状态取证、证据评估、诊断检查和人工确认串成可追溯链路，解决通用大模型“懂概念但不懂这台机器”的问题。

**核心工作：**

- **混合检索与重排序**：以 BM25 与 Dense 双路召回、RRF（`k=60`）融合、Cross-Encoder/lexical 重排构建知识检索链路，并用 Qdrant 按 `document_id` 先删后写；解决单一检索对命令、报错码等专有术语召回不稳，以及重复入库残留旧切片的问题；实现知识片段带 `document_id`、`chunk_id`、章节、来源和适用版本返回，可被最终答案引用。
- **LangGraph 诊断闭环**：用状态图编排五路诊断策略和 Planner → Executor → Critic → 定向修正流程，把 Critic 放在答案生成之前，以最大修正轮数和计划指纹限制循环；解决一次性诊断漏工具、漏知识、重复规划和无限重试的问题；实现 nginx、RPM、Supervisor、ELK 四类场景可完成“计划—工具—检查—答案—引用”闭环。
- **知识与工具证据融合**：设计统一 `EvidenceItem` 与 `Citation`，让知识片段和工具结果进入同一证据列表，并由 `sufficiency` 节点计算证据缺口；解决 AGENT 路径只依赖工具结果、引用来源不完整、模型结论容易超出证据的问题；实现最终答案同时引用知识库和工具 locator，证据不足时由代码添加提示，而不是依赖模型自觉。
- **能力化运维工具体系**：用 Pydantic Schema 定义工具参数、风险等级和只读属性，接入 systemd、RPM、Supervisor、Elasticsearch、Logstash 等 16/17 个工具，统一超时、主机白名单、失败状态和 fallback；解决模型生成任意 Shell、工具失败被误标成功、ES 查询被静默退化成本地 journal 的问题；实现四类运维场景可组合调用并保留结构化 `tool_trace`。
- **Redis 状态管理与人工确认**：用 Redis 承载检索缓存、用户限流和待确认动作，确认卡绑定 `session_id + user_id`，通过 Lua 原子消费、TTL 和 `used` 标记保证只执行一次，并配合幂等键防止重复提交；解决多实例、双击确认导致写操作重复执行的问题；实现“发起确认 → 人工确认 → 执行一次 → 重复提交 409”的完整链路，Redis 不可用时返回 503 而不是降级到进程内字典。
- **FastAPI + React 业务闭环**：提供 `/chat`、`/chat/stream`、诊断记录、知识、工具和监控接口，前端实现工作台、知识库、工具管理、诊断记录、Agent 执行记录、系统监控六个页面；解决 Agent 过程不可见、排障结果不可复核的问题；实现计划、工具轨迹、Critic 结果、引用和证据缺口可在页面查看，SSE 的 `node` 事件反映真实节点进度，`token` 事件按 48 字符切片推送答案内容。

## 使用说明

- 投递 Java 后端岗位时，可把“FastAPI + React”一条改写为“REST 接口与前端业务闭环”，对外说明本项目后端使用 Python/FastAPI；不要为了匹配 JD 改写技术栈事实。
- 投递 AI 应用开发岗位时，建议保留前三条，把工具与 Redis 两条压缩为一条，突出 RAG、Agent 工作流和证据融合。

## 30 秒项目介绍版

> OpsPilot 是我做的一个国产操作系统智能运维项目。它把 RAG 和 Agent 结合起来：一边检索运维手册，一边通过能力化工具查服务状态、日志、RPM 和 ELK；中间用 LangGraph 做 Planner、Executor、Critic，最后答案同时带知识引用和工具证据。写操作比如重启服务，必须走 Redis 的一次性人工确认。项目重点不是做一个聊天框，而是让诊断过程可计划、可检查、可追溯。

## 90 秒项目介绍版

> 这个项目解决的痛点是：大模型能讲 systemd 原理，但不知道目标机器上的 nginx 为什么起不来。我的做法是把知识证据和现场证据统一起来。
>
> 检索侧用 BM25 加 Dense，RRF 融合，再用 Cross-Encoder 重排；知识切片保留文档、章节、来源和适用版本，所以最终引用能落到原文。Agent 侧用 LangGraph 编排五路策略，AGENT 路径先检索知识，再让 Planner 生成工具计划，Executor 执行，Critic 在答案生成前检查计划覆盖、工具失败、证据类型和冲突；不通过就在两轮内补检索或重规划。
>
> 工具全部是能力化工具，模型不能拼 Shell；每个工具都有 Schema、风险等级、超时和主机白名单。重启这类写操作默认不注册，开启后也要人工确认，Redis 用 Lua 原子消费，保证只执行一次。
>
> 目前四类场景都能完整跑通，六个页面能看计划、工具轨迹、Critic 和引用。
