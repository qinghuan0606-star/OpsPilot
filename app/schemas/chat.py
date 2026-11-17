"""Chat request/response, action proposal and execution-trace schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.enums import (
    IntentLabel,
    QueryComplexity,
    RetrievalStrategy,
    ToolExecutionStatus,
    ToolRisk,
)
from app.schemas.agent import AgentPlan
from app.schemas.common import LatencyBreakdown, TokenUsage
from app.schemas.critic import CriticResult
from app.schemas.retrieval import Citation


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    name: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)
    user_id: str = Field(default="anonymous", min_length=1, max_length=64)
    stream: bool = False
    confirm_action_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class ActionProposal(BaseModel):
    action_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk: ToolRisk
    summary: str


class ToolTraceItem(BaseModel):
    """One executed tool call, surfaced to the UI for the agent timeline."""

    step_id: int = 0
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    status: ToolExecutionStatus = ToolExecutionStatus.OK
    risk: ToolRisk = ToolRisk.READ
    latency_ms: float = 0.0
    error: str | None = None
    fallback_from: str | None = None
    executed_tool: str | None = None
    failure_kind: str | None = None
    idempotent: bool = False


class RetrievalDetail(BaseModel):
    """What the retriever actually did, for the workbench evidence panel."""

    rewritten_queries: list[str] = Field(default_factory=list)
    top_k: int = 0
    knowledge_hits: int = 0
    reranked: list[Citation] = Field(default_factory=list)
    rounds: int = 1


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    trace_id: str
    intent: IntentLabel | None = None
    complexity: QueryComplexity | None = None
    strategy: RetrievalStrategy | None = None
    execution_status: Literal["completed", "pending_confirmation", "refused", "error"] = "completed"
    plan: AgentPlan | None = None
    critic_result: CriticResult | None = None
    critic_round: int = 0
    citations: list[Citation] = Field(default_factory=list)
    pending_action: ActionProposal | None = None
    refused: bool = False
    error_code: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency: LatencyBreakdown = Field(default_factory=LatencyBreakdown)
    # Evidence honesty: the caller must be able to tell a confirmed diagnosis
    # from a partial one. Both flags are computed by code, never by the prompt.
    evidence_sufficient: bool = True
    evidence_gaps: list[str] = Field(default_factory=list)
    tool_trace: list[ToolTraceItem] = Field(default_factory=list)
    retrieval_detail: RetrievalDetail | None = None
