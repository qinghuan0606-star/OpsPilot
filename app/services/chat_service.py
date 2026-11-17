"""Chat orchestration: graph execution, streaming and persistence."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import build_graph
from app.agents.state import AgentState
from app.config.settings import Settings
from app.core.exceptions import (
    AppError,
    ConfirmationStoreUnavailableError,
    GuardrailError,
    RateLimitError,
)
from app.core.ids import new_id
from app.core.request_scope import request_session
from app.infra.rate_limit import RateLimiter
from app.observability.metrics import REQUEST_LATENCY, REQUESTS, ROUTING, STAGE_LATENCY, TOKEN_USAGE
from app.providers.base import LLMProvider
from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.session_repository import SessionRepository
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import DocumentReranker
from app.schemas.chat import ActionProposal, ChatRequest, ChatResponse, RetrievalDetail
from app.schemas.common import LatencyBreakdown, TokenUsage
from app.schemas.retrieval import Citation
from app.services.pending_store import PendingActionStore, build_pending_store
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_STORE_DOWN_ANSWER = (
    "确认服务不可用（Redis 未就绪），为避免重复执行，本次操作没有发起确认，也没有执行任何变更。"
)


def _knowledge_only_registry(retriever: HybridRetriever) -> ToolRegistry:
    """Last-resort registry: knowledge search only.

    The container always injects the full ops registry; this fallback exists so a
    hand-built service in a test cannot silently gain host access.
    """
    from app.tools.support_tools import SearchKnowledgeTool

    registry = ToolRegistry()
    registry.register(SearchKnowledgeTool(retriever))
    return registry


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMProvider,
        retriever: HybridRetriever,
        reranker: DocumentReranker,
        session_factory: async_sessionmaker[AsyncSession],
        rate_limiter: RateLimiter,
        registry: ToolRegistry | None = None,
        redis=None,
        pending_store: PendingActionStore | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._retriever = retriever
        self._reranker = reranker
        self._session_factory = session_factory
        self._rate_limiter = rate_limiter
        self.registry = registry or _knowledge_only_registry(retriever)
        self._pending_store = pending_store or build_pending_store(settings, redis)
        self._graph = build_graph(
            llm=llm,
            settings=settings,
            retriever=retriever,
            reranker=reranker,
            registry=self.registry,
        )

    async def chat(self, request: ChatRequest, *, trace_id: str) -> ChatResponse:
        await self._enforce_rate_limit(request.user_id)
        started = time.perf_counter()
        session_id = request.session_id or new_id("sess_")
        async with request_session(self._session_factory) as db:
            state = await self._initial_state(db, request, session_id, trace_id)
            result = await self._invoke(state)
            response = self._to_response(result, session_id=session_id, trace_id=trace_id)
            response = await self._remember_pending(request, response)
            await self._persist(db, request, response, summary=result.get("summary") or "")
            await db.commit()
        self._observe(response, started)
        return response

    async def stream(self, request: ChatRequest, *, trace_id: str) -> AsyncIterator[dict]:
        """Pseudo-streaming SSE.

        `node` events report real graph progress; `token` events are 48-char
        slices of the already-final answer. There is no token-by-token LLM
        streaming anywhere in this path and the API must not claim otherwise.
        """
        await self._enforce_rate_limit(request.user_id)
        started = time.perf_counter()
        session_id = request.session_id or new_id("sess_")
        async with request_session(self._session_factory) as db:
            state = await self._initial_state(db, request, session_id, trace_id)
            yield {"event": "started", "trace_id": trace_id}
            queue: asyncio.Queue[dict | None] = asyncio.Queue()
            holder: dict = {"merged": dict(state), "guardrail": None, "error": None}

            async def _run_graph() -> None:
                try:
                    async for update in self._graph.astream(state, stream_mode="updates"):
                        for node, payload in update.items():
                            if isinstance(payload, dict):
                                holder["merged"].update(payload)
                            event: dict = {"event": "node", "node": node}
                            if isinstance(payload, dict) and payload.get("intent"):
                                event["intent"] = payload["intent"].label.value
                            if isinstance(payload, dict) and payload.get("strategy"):
                                event["strategy"] = payload["strategy"].value
                            if isinstance(payload, dict) and payload.get("tool_trace"):
                                event["tool_trace"] = [
                                    item.model_dump(mode="json") for item in payload["tool_trace"]
                                ]
                            if isinstance(payload, dict) and "evidence_sufficient" in payload:
                                event["evidence_sufficient"] = payload["evidence_sufficient"]
                                event["evidence_gaps"] = payload.get("evidence_gaps") or []
                            await queue.put(event)
                except GuardrailError as exc:
                    holder["guardrail"] = exc
                except Exception as exc:  # graph failures surface after the queue drains
                    holder["error"] = exc
                finally:
                    await queue.put(None)

            task = asyncio.create_task(_run_graph())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield item
                await task
            finally:
                if not task.done():
                    task.cancel()

            if holder["guardrail"] is not None:
                exc = holder["guardrail"]
                await db.commit()
                yield {
                    "event": "answer",
                    "data": ChatResponse(
                        answer=exc.message,
                        session_id=session_id,
                        trace_id=trace_id,
                        refused=True,
                        error_code=exc.error_code.value,
                    ).model_dump(mode="json"),
                }
                yield {"event": "done", "trace_id": trace_id}
                return
            if holder["error"] is not None:
                raise holder["error"]
            merged: AgentState = holder["merged"]
            response = self._to_response(merged, session_id=session_id, trace_id=trace_id)
            response = await self._remember_pending(request, response)
            await self._persist(db, request, response, summary=merged.get("summary") or "")
            await db.commit()
        self._observe(response, started)
        # Pseudo-streaming: slice a finished answer; never emit the LLM JSON
        # envelope or an answer that the faithfulness node may still replace.
        for index in range(0, len(response.answer), 48):
            yield {"event": "token", "text": response.answer[index : index + 48]}
        yield {"event": "answer", "data": response.model_dump(mode="json")}
        yield {"event": "done", "trace_id": trace_id}

    async def _enforce_rate_limit(self, user_id: str) -> None:
        allowed = await self._rate_limiter.allow(f"user:{user_id}")
        if not allowed:
            raise RateLimitError()

    async def _initial_state(
        self,
        db: AsyncSession,
        request: ChatRequest,
        session_id: str,
        trace_id: str,
    ) -> AgentState:
        confirmed_action = await self._resolve_confirmation(request, session_id)
        sessions = SessionRepository(db)
        await sessions.get_or_create(session_id, request.user_id)
        history = await sessions.recent_messages(session_id)
        return {
            "trace_id": trace_id,
            "session_id": session_id,
            "user_id": request.user_id,
            "user_query": request.message,
            "messages": history,
            "summary": "",
            "retrieved_chunks": [],
            "evidence": [],
            "evidence_sufficient": True,
            "evidence_gaps": [],
            "retrieval_round": 0,
            "retrieval_queries": [],
            "needs_tools": False,
            "host_id": self._settings.ops_default_host,
            "plan": None,
            "plan_fingerprint": None,
            "plan_history": [],
            "tool_results": [],
            "tool_trace": [],
            "critic_result": None,
            "critic_round": 0,
            "critic_feedback": [],
            "pending_action": None,
            "confirmed_action": confirmed_action,
            "confirm_action_id": request.confirm_action_id,
            "idempotency_key": request.idempotency_key,
            "citations": [],
            "refused": False,
            "step_count": 0,
            "token_usage": TokenUsage(),
            "latency": LatencyBreakdown(),
            "extra": {},
        }

    async def _resolve_confirmation(
        self, request: ChatRequest, session_id: str
    ) -> ActionProposal | None:
        if not request.confirm_action_id:
            return None
        return await self._pending_store.consume(
            request.confirm_action_id, session_id=session_id, user_id=request.user_id
        )

    async def _remember_pending(self, request: ChatRequest, response: ChatResponse) -> ChatResponse:
        action = response.pending_action
        if action is None:
            return response
        try:
            await self._pending_store.save(
                action, session_id=response.session_id, user_id=request.user_id
            )
        except ConfirmationStoreUnavailableError as exc:
            return response.model_copy(
                update={
                    "answer": _STORE_DOWN_ANSWER,
                    "pending_action": None,
                    "refused": True,
                    "error_code": exc.error_code.value,
                    "evidence_sufficient": False,
                    "evidence_gaps": [*response.evidence_gaps, "人工确认存储不可用"],
                }
            )
        return response

    async def _invoke(self, state: AgentState) -> AgentState:
        try:
            # LangGraph widens the state to dict[str, Any]; the graph contract is AgentState.
            return cast(AgentState, await self._graph.ainvoke(state))
        except GuardrailError as exc:
            return {
                **state,
                "final_answer": exc.message,
                "refused": True,
                "error": exc.error_code.value,
            }
        except AppError:
            raise

    async def _persist(
        self,
        db: AsyncSession,
        request: ChatRequest,
        response: ChatResponse,
        *,
        summary: str = "",
    ) -> None:
        sessions = SessionRepository(db)
        await sessions.append_message(response.session_id, "user", request.message)
        await sessions.append_message(response.session_id, "assistant", response.answer)
        if summary:
            await sessions.save_summary(response.session_id, summary)
        await DiagnosisRepository(db).record(
            response, user_id=request.user_id, query=request.message
        )

    def _retrieval_detail(self, result: AgentState) -> RetrievalDetail | None:
        chunks = result.get("retrieved_chunks") or []
        evidence = result.get("evidence") or []
        if not chunks and not evidence:
            return None
        knowledge: list[Citation] = [
            Citation(
                citation_id=item.evidence_id,
                kind="knowledge",
                document_id=item.metadata.get("document_id", ""),
                title=item.title,
                chunk_id=item.reference,
                section=item.metadata.get("section") or None,
                locator=item.reference,
                excerpt=item.excerpt,
            )
            for item in evidence
            if item.kind.value == "knowledge"
        ]
        return RetrievalDetail(
            rewritten_queries=list(result.get("rewritten_queries") or []),
            top_k=len(chunks),
            knowledge_hits=len(knowledge),
            reranked=knowledge[:8],
            rounds=int(result.get("retrieval_round") or 1),
        )

    def _to_response(
        self,
        result: AgentState,
        *,
        session_id: str,
        trace_id: str,
    ) -> ChatResponse:
        answer = result.get("final_answer") or "暂时无法回答，请稍后重试。"
        strategy = result.get("strategy")
        intent = result.get("intent")
        execution_status: Literal["completed", "pending_confirmation", "refused", "error"]
        if result.get("refused"):
            execution_status = "refused"
        elif result.get("pending_action") is not None:
            execution_status = "pending_confirmation"
        elif result.get("error"):
            execution_status = "error"
        else:
            execution_status = "completed"
        return ChatResponse(
            answer=answer,
            session_id=session_id,
            trace_id=trace_id,
            intent=intent.label if intent else None,
            complexity=result.get("query_complexity"),
            strategy=strategy,
            execution_status=execution_status,
            plan=result.get("plan"),
            critic_result=result.get("critic_result"),
            critic_round=int(result.get("critic_round") or 0),
            citations=result.get("citations") or [],
            pending_action=result.get("pending_action"),
            refused=bool(result.get("refused")),
            error_code=result.get("error"),
            token_usage=result.get("token_usage") or TokenUsage(),
            latency=result.get("latency") or LatencyBreakdown(),
            evidence_sufficient=bool(result.get("evidence_sufficient", True)),
            evidence_gaps=list(result.get("evidence_gaps") or []),
            tool_trace=list(result.get("tool_trace") or []),
            retrieval_detail=self._retrieval_detail(result),
        )

    def _observe(self, response: ChatResponse, started: float) -> None:
        total_ms = (time.perf_counter() - started) * 1000
        response.latency.total_ms = total_ms
        REQUESTS.labels(
            strategy=(response.strategy.value if response.strategy else "unknown"),
            intent=(response.intent.value if response.intent else "unknown"),
            status="ok" if not response.refused else "refused",
        ).inc()
        if response.strategy:
            ROUTING.labels(strategy=response.strategy.value).inc()
        REQUEST_LATENCY.observe(total_ms / 1000)
        STAGE_LATENCY.labels(stage="intent").observe(response.latency.intent_ms / 1000)
        STAGE_LATENCY.labels(stage="retrieval").observe(response.latency.retrieval_ms / 1000)
        STAGE_LATENCY.labels(stage="llm").observe(response.latency.llm_ms / 1000)
        TOKEN_USAGE.labels(kind="total").inc(response.token_usage.total_tokens)
        logger.info(
            "chat_completed",
            extra={
                "trace_id": response.trace_id,
                "strategy": response.strategy.value if response.strategy else None,
                "intent": response.intent.value if response.intent else None,
                "evidence_sufficient": response.evidence_sufficient,
                "latency_ms": round(total_ms, 1),
            },
        )
