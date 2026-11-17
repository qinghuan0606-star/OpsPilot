"""Diagnosis run persistence for the history and agent-trace pages."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import DiagnosisRow, DiagnosisTraceRow
from app.schemas.chat import ChatResponse


class DiagnosisRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record(self, response: ChatResponse, *, user_id: str, query: str) -> None:
        self._db.add(
            DiagnosisRow(
                trace_id=response.trace_id,
                session_id=response.session_id,
                user_id=user_id,
                query=query[:4000],
                intent=response.intent.value if response.intent else "",
                strategy=response.strategy.value if response.strategy else "",
                answer=response.answer[:4000],
                citations_json=json.dumps(
                    [c.model_dump(mode="json") for c in response.citations], ensure_ascii=False
                ),
                tool_trace_json=json.dumps(
                    [t.model_dump(mode="json") for t in response.tool_trace], ensure_ascii=False
                ),
                retrieval_json=json.dumps(
                    response.retrieval_detail.model_dump(mode="json")
                    if response.retrieval_detail
                    else {},
                    ensure_ascii=False,
                ),
                evidence_sufficient=response.evidence_sufficient,
                evidence_gaps=";".join(response.evidence_gaps),
                refused=response.refused,
                latency_json=response.latency.model_dump_json(),
            )
        )
        self._db.add(
            DiagnosisTraceRow(
                trace_id=response.trace_id,
                plan_json=json.dumps(
                    response.plan.model_dump(mode="json") if response.plan else {},
                    ensure_ascii=False,
                ),
                critic_json=json.dumps(
                    response.critic_result.model_dump(mode="json")
                    if response.critic_result
                    else {},
                    ensure_ascii=False,
                ),
                critic_round=response.critic_round,
                execution_status=response.execution_status,
            )
        )

    async def recent_with_traces(
        self, limit: int = 20
    ) -> list[tuple[DiagnosisRow, DiagnosisTraceRow | None]]:
        result = await self._db.execute(
            select(DiagnosisRow, DiagnosisTraceRow)
            .outerjoin(DiagnosisTraceRow, DiagnosisTraceRow.trace_id == DiagnosisRow.trace_id)
            .order_by(DiagnosisRow.created_at.desc())
            .limit(limit)
        )
        return [(row, trace) for row, trace in result.all()]

    async def get_with_trace(
        self, trace_id: str
    ) -> tuple[DiagnosisRow, DiagnosisTraceRow | None] | None:
        result = await self._db.execute(
            select(DiagnosisRow, DiagnosisTraceRow)
            .outerjoin(DiagnosisTraceRow, DiagnosisTraceRow.trace_id == DiagnosisRow.trace_id)
            .where(DiagnosisRow.trace_id == trace_id)
        )
        pair = result.first()
        return (pair[0], pair[1]) if pair is not None else None

    async def recent(self, limit: int = 20) -> list[DiagnosisRow]:
        result = await self._db.execute(
            select(DiagnosisRow).order_by(DiagnosisRow.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get(self, trace_id: str) -> DiagnosisRow | None:
        result = await self._db.execute(
            select(DiagnosisRow).where(DiagnosisRow.trace_id == trace_id)
        )
        return result.scalar_one_or_none()
