"""Document retrieval node producing unified evidence."""

from __future__ import annotations

import time

from app.agents.state import AgentState
from app.config.settings import Settings
from app.core.enums import RetrievalStrategy
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_rewrite import QueryRewriter
from app.retrieval.reranker import DocumentReranker
from app.retrieval.self_rag import SelfRAGLoop
from app.schemas.common import LatencyBreakdown
from app.schemas.evidence import EvidenceItem, knowledge_evidence
from app.schemas.retrieval import RetrievedChunk


def _normalise_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _merge_knowledge_evidence(
    existing: list[EvidenceItem], chunks: list[RetrievedChunk]
) -> list[EvidenceItem]:
    """Append knowledge evidence without duplicating already-cited chunks.

    On a second retrieval round the earlier evidence keeps its rank so citations
    stay stable, while new chunks fill the tail.
    """
    seen = {item.evidence_id for item in existing if item.kind.value == "knowledge"}
    merged = list(existing)
    for chunk in chunks:
        item = knowledge_evidence(chunk)
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        merged.append(item)
    return merged


async def retrieval_node(
    state: AgentState,
    *,
    retriever: HybridRetriever,
    reranker: DocumentReranker,
    rewriter: QueryRewriter,
    self_rag: SelfRAGLoop,
    settings: Settings,
) -> dict:
    started = time.perf_counter()
    base_query = state["user_query"]
    # Second round uses the gap-focused query built by the critic/sufficiency node.
    query = str(state.get("gap_query") or base_query)
    seen_queries = list(state.get("retrieval_queries") or [])
    if _normalise_query(query) in seen_queries:
        # The critic asked for a query already sent. Do not duplicate embedding,
        # BM25 and rerank work; the next critic pass will explain the gap.
        return {"retrieval_queries": seen_queries}
    strategy = state.get("strategy")
    top_k = (
        settings.retrieval_top_k_complex
        if strategy == RetrievalStrategy.MULTI
        else settings.retrieval_top_k_simple
    )
    if strategy == RetrievalStrategy.MULTI and not state.get("retrieval_round"):
        chunks = await self_rag.retrieve(base_query, top_k=top_k)
        rewritten = [base_query]
    else:
        suggestions = await rewriter.rewrite(query)
        rewritten = list(dict.fromkeys([query, *suggestions]))[:2]
        by_id: dict[str, RetrievedChunk] = {}
        for search_query in rewritten:
            for candidate in await retriever.retrieve(search_query, top_k=top_k):
                by_id.setdefault(candidate.chunk_id, candidate)
        chunks = await reranker.rerank(query, list(by_id.values()), top_n=settings.rerank_top_n)
    evidence = _merge_knowledge_evidence(state.get("evidence") or [], chunks)
    latency = state.get("latency") or LatencyBreakdown()
    latency.retrieval_ms = (time.perf_counter() - started) * 1000
    for sent in [query, *rewritten]:
        normalised = _normalise_query(sent)
        if normalised and normalised not in seen_queries:
            seen_queries.append(normalised)
    return {
        "retrieved_chunks": chunks,
        "rewritten_queries": rewritten,
        "retrieval_queries": seen_queries,
        "evidence": evidence,
        "retrieval_round": int(state.get("retrieval_round") or 0) + 1,
        "latency": latency,
    }
