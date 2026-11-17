"""Diagnosis record exposed by the operations history pages."""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.chat import RetrievalDetail, ToolTraceItem
from app.schemas.retrieval import Citation


class DiagnosisRecord(BaseModel):
    trace_id: str
    session_id: str = ""
    user_id: str = ""
    query: str
    intent: str | None = None
    strategy: str | None = None
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    tool_trace: list[ToolTraceItem] = Field(default_factory=list)
    retrieval_detail: RetrievalDetail | None = None
    evidence_sufficient: bool = True
    evidence_gaps: list[str] = Field(default_factory=list)
    refused: bool = False
    latency: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class DiagnosisListResponse(BaseModel):
    items: list[DiagnosisRecord] = Field(default_factory=list)
    total: int = 0
