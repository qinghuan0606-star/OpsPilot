"""Shared agent state passed between graph nodes."""

from typing import Any, TypedDict

from app.core.enums import QueryComplexity, RetrievalStrategy
from app.schemas.agent import AgentPlan, ComplexityResult, IntentResult, ToolResult
from app.schemas.chat import ActionProposal, ChatMessage, ToolTraceItem
from app.schemas.common import LatencyBreakdown, TokenUsage
from app.schemas.critic import CriticResult
from app.schemas.evidence import EvidenceItem
from app.schemas.retrieval import Citation, RetrievedChunk


class AgentState(TypedDict, total=False):
    """LangGraph state. Partial updates replace listed keys; no infinite append reducer.

    Messages are compressed explicitly in the memory node instead of Annotated[add]
    so the graph cannot silently blow the 128k budget.
    """

    trace_id: str
    session_id: str
    user_id: str
    user_query: str
    messages: list[ChatMessage]
    summary: str
    intent: IntentResult | None
    complexity: ComplexityResult | None
    strategy: RetrievalStrategy | None
    query_complexity: QueryComplexity | None
    rewritten_queries: list[str]
    retrieved_chunks: list[RetrievedChunk]
    # Unified evidence: knowledge chunks and tool results land in one list so
    # citations work on the AGENT path too.
    evidence: list[EvidenceItem]
    evidence_sufficient: bool
    evidence_gaps: list[str]
    retrieval_round: int
    # Normalised queries already sent to the retriever, so a critic-triggered
    # correction cannot repeat the exact same retrieval.
    retrieval_queries: list[str]
    needs_tools: bool
    host_id: str | None
    plan: AgentPlan | None
    plan_fingerprint: str | None
    # Fingerprints from earlier plans in this run, used to reject replans that
    # would execute exactly the same tools again.
    plan_history: list[str]
    tool_results: list[ToolResult]
    tool_trace: list[ToolTraceItem]
    # Diagnosis critic (pre-answer): plan coverage, tool status, evidence kinds,
    # structured contradictions, and the correction action.
    critic_result: CriticResult | None
    critic_round: int
    critic_feedback: list[str]
    pending_action: ActionProposal | None
    confirmed_action: ActionProposal | None
    confirm_action_id: str | None
    idempotency_key: str | None
    final_answer: str | None
    citations: list[Citation]
    refused: bool
    error: str | None
    step_count: int
    token_usage: TokenUsage
    latency: LatencyBreakdown
    extra: dict[str, Any]
