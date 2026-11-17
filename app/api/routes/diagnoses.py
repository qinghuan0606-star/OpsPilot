"""Diagnosis history and agent execution trace endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_container
from app.core.request_scope import request_session
from app.repositories.diagnosis import DiagnosisRepository
from app.services.container import AppContainer

router = APIRouter(tags=["diagnoses"])


def _json_or_none(raw: str | None) -> dict | None:
    value = json.loads(raw or "{}")
    return value if value else None


def _row_payload(row, trace=None) -> dict:
    return {
        "trace_id": row.trace_id,
        "session_id": row.session_id,
        "user_id": row.user_id,
        "query": row.query,
        "intent": row.intent,
        "strategy": row.strategy,
        "answer": row.answer,
        "citations": json.loads(row.citations_json or "[]"),
        "tool_trace": json.loads(row.tool_trace_json or "[]"),
        "retrieval": json.loads(row.retrieval_json or "{}"),
        "evidence_sufficient": row.evidence_sufficient,
        "evidence_gaps": [g for g in (row.evidence_gaps or "").split(";") if g],
        "refused": row.refused,
        "latency": json.loads(row.latency_json or "{}"),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "execution_status": (
            trace.execution_status
            if trace is not None
            else ("refused" if row.refused else "completed")
        ),
        "plan": _json_or_none(trace.plan_json) if trace is not None else None,
        "critic_result": _json_or_none(trace.critic_json) if trace is not None else None,
        "critic_round": trace.critic_round if trace is not None else 0,
    }


@router.get("/diagnoses")
async def list_diagnoses(
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
) -> dict:
    async with request_session(container.session_factory) as db:
        rows = await DiagnosisRepository(db).recent_with_traces(limit)
        items = [_row_payload(row, trace) for row, trace in rows]
    return {"items": items, "count": len(items)}


@router.get("/diagnoses/{trace_id}")
async def get_diagnosis(
    trace_id: str,
    container: AppContainer = Depends(get_container),
) -> dict:
    async with request_session(container.session_factory) as db:
        pair = await DiagnosisRepository(db).get_with_trace(trace_id)
    if pair is None:
        return {"found": False, "trace_id": trace_id}
    row, trace = pair
    return {"found": True, "item": _row_payload(row, trace)}
