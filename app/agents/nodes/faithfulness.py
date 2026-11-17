"""Self-RAG faithfulness check and answer self-correction.

Works on the unified evidence list, so an AGENT diagnosis is verified against
the tool results it actually used, not only against knowledge chunks.
"""

from __future__ import annotations

from app.agents.nodes.generate import (
    AnswerPayload,
    _evidence_block,
    _tool_text,
    citations_from_evidence,
)
from app.agents.state import AgentState
from app.core.enums import RetrievalStrategy
from app.core.exceptions import LLMOutputError, LLMProviderError
from app.guardrails.hallucination import FaithfulnessChecker, FaithfulnessResult
from app.observability.metrics import HALLUCINATION_FLAGS
from app.prompts.faithfulness import SELF_CORRECT_SYSTEM, SELF_CORRECT_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import parse_model
from app.schemas.retrieval import RetrievedChunk

_NO_EVIDENCE_ANSWER = (
    "现有证据不足，暂时无法给出可靠结论。"
    "请补充主机名、服务名或具体报错，或授权查询服务状态与日志后再试。"
)


async def self_correct_answer(
    *,
    llm: LLMProvider,
    checker: FaithfulnessChecker,
    query: str,
    answer: str,
    chunks: list[RetrievedChunk],
    evidence_text: str,
    tool_results_text: str,
    first_result: FaithfulnessResult,
) -> tuple[str, FaithfulnessResult, bool]:
    """LLM rewrite once, then extractive fallback. Returns (answer, judge, corrected)."""
    try:
        response = await llm.generate(
            [
                {"role": "system", "content": SELF_CORRECT_SYSTEM},
                {
                    "role": "user",
                    "content": SELF_CORRECT_USER.format(
                        query=query,
                        answer=answer,
                        critique=first_result.rationale
                        or ",".join(first_result.hallucinated_spans),
                        evidence=evidence_text,
                        tool_results=tool_results_text or "(无)",
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        rewritten = parse_model(response.content, AnswerPayload).answer
        judged = await checker.check(
            query=query,
            answer=rewritten,
            chunks=chunks,
            tool_results_text=tool_results_text,
            evidence_text=evidence_text,
        )
        if judged.supported:
            return rewritten, judged, True
    except (LLMProviderError, LLMOutputError):
        pass
    patched = _extractive_fallback(evidence_text, tool_results_text)
    judged = await checker.check(
        query=query,
        answer=patched,
        chunks=chunks,
        tool_results_text=tool_results_text,
        evidence_text=evidence_text,
    )
    return patched, judged, True


def _extractive_fallback(evidence_text: str, tool_results_text: str) -> str:
    """Quoted excerpt only; never a paraphrase of missing facts."""
    if evidence_text and evidence_text != "(无证据)":
        first = evidence_text.split("\n\n")[0]
        return f"以下结论仅基于已获取证据，请核对原文：\n\n{first[:300]}"
    if tool_results_text and tool_results_text != "(无)":
        return "已获取主机数据，但无法将其归并为可靠结论。请查看下方工具执行记录。"
    return _NO_EVIDENCE_ANSWER


async def faithfulness_node(
    state: AgentState, checker: FaithfulnessChecker, llm: LLMProvider
) -> dict:
    answer = state.get("final_answer") or ""
    extra_state = state.get("extra") or {}
    if state.get("refused") or state.get("pending_action") or extra_state.get("missing_target"):
        return {}
    evidence = state.get("evidence") or []
    chunks = state.get("retrieved_chunks") or []
    tools = state.get("tool_results") or []
    if isinstance(llm, OfflineLLMProvider) or state.get("strategy") == RetrievalStrategy.DIRECT:
        return {}
    if not evidence:
        return {
            "final_answer": _NO_EVIDENCE_ANSWER,
            "citations": [],
            "refused": True,
            "evidence_sufficient": False,
        }
    evidence_text = _evidence_block(evidence, limit=10)
    tool_text = _tool_text(tools)
    result = await checker.check(
        query=state["user_query"],
        answer=answer,
        chunks=chunks,
        tool_results_text=tool_text,
        evidence_text=evidence_text,
    )
    extra = {"faithfulness": result.model_dump(), "self_corrected": False}
    if result.supported:
        return {"extra": {**(state.get("extra") or {}), **extra}}
    HALLUCINATION_FLAGS.inc()
    if result.rationale == "checker_unavailable":
        fallback_answer = _extractive_fallback(evidence_text, tool_text)
        selected = {item.evidence_id for item in evidence[:3]}
        return {
            "final_answer": fallback_answer,
            "citations": citations_from_evidence(evidence, selected),
            "extra": {**(state.get("extra") or {}), **extra},
        }
    patched, judged, corrected = await self_correct_answer(
        llm=llm,
        checker=checker,
        query=state["user_query"],
        answer=answer,
        chunks=chunks,
        evidence_text=evidence_text,
        tool_results_text=tool_text,
        first_result=result,
    )
    extra = {"faithfulness": judged.model_dump(), "self_corrected": corrected}
    if not judged.supported:
        return {
            "final_answer": _NO_EVIDENCE_ANSWER,
            "citations": [],
            "refused": True,
            "evidence_sufficient": False,
            "extra": {**(state.get("extra") or {}), **extra},
        }
    return {
        "final_answer": patched,
        "citations": citations_from_evidence(evidence, {i.evidence_id for i in evidence[:4]}),
        "extra": {**(state.get("extra") or {}), **extra},
    }
