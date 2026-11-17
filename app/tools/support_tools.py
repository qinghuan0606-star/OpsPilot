"""Support tools: knowledge search and human handoff."""

from pydantic import BaseModel, Field

from app.core.enums import DocumentCategory, ToolRisk
from app.retrieval.hybrid import HybridRetriever
from app.schemas.agent import ToolResult
from app.tools.base import Tool, ToolContext


class KnowledgeSearchInput(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=200,
        description="检索问句，如「nginx 升级后模块加载失败」；不要填主机名或包名代替问题",
    )
    category: DocumentCategory | None = Field(
        default=None, description="可选知识域过滤，如 rpm_package、service_mgmt"
    )


class SearchKnowledgeTool(Tool):
    name = "search_knowledge"
    description = (
        "检索运维知识库（Linux 基础、国产操作系统文档、RPM、服务管理、日志与故障案例、"
        "网络磁盘、安全权限）并返回原文片段。只读，不查真实主机。"
        "何时用：查规则/手册/命令用法/故障案例；解释 load_module 失败、依赖冲突等概念。"
        "何时不用：查某台主机的真实状态、版本、日志请用 get_* 运维工具。"
        "参数 query 为检索问句；category 可选知识域。"
        "返回 chunks[{chunk_id,title,content,section,source_type}]，content 已截断，只作知识依据。"
    )
    risk = ToolRisk.READ
    input_model = KnowledgeSearchInput

    def __init__(self, retriever: HybridRetriever) -> None:
        self._retriever = retriever

    async def execute(self, parsed: KnowledgeSearchInput, context: ToolContext) -> ToolResult:
        chunks = await self._retriever.retrieve(parsed.query, top_k=4)
        payload = [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "title": c.title,
                "content": c.content[:400],
                "section": c.section,
                "category": c.category.value,
                "source_type": c.metadata.get("source_type", ""),
            }
            for c in chunks
        ]
        return ToolResult(
            name=self.name, success=True, output={"query": parsed.query, "chunks": payload}
        )


class EscalateInput(BaseModel):
    reason: str = Field(
        min_length=1,
        max_length=200,
        description="转人工原因摘要，如「需要变更窗口内由管理员重启服务」",
    )


class EscalateToHumanTool(Tool):
    name = "escalate_to_human"
    description = (
        "创建转人工工单进入运维值班队列。不查询主机、不解答知识问题。"
        "何时用：需要人工审批的变更、工具无法覆盖、涉及生产权限或敏感操作。"
        "何时不用：能只读查询就先查；普通知识问答不要转人工。"
        "参数 reason 概括原因。返回 ticket_id 与 queue=ops_shift，表示已排队而非已接通。"
    )
    risk = ToolRisk.EXTERNAL
    input_model = EscalateInput

    async def execute(self, parsed: EscalateInput, context: ToolContext) -> ToolResult:
        return ToolResult(
            name=self.name,
            success=True,
            output={
                "ticket_id": f"ops_t_{context.session_id[:10]}",
                "queue": "ops_shift",
                "reason": parsed.reason,
                "evidence": {
                    "title": "转人工工单已登记",
                    "locator": f"ticket:{context.session_id[:10]}",
                    "excerpt": parsed.reason,
                },
            },
            risk=self.risk,
        )
