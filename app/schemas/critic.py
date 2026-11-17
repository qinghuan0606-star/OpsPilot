"""Diagnosis critic result: plan/evidence readiness before answer generation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CriticAction = Literal["accept", "retrieve", "plan", "clarify"]
CriticSeverity = Literal["blocking", "warning"]
CriticIssueCode = Literal[
    "missing_knowledge",
    "missing_tool",
    "tool_failed",
    "fallback_warning",
    "target_mismatch",
    "evidence_conflict",
    "missing_target",
    "plan_repeat",
]


class CriticIssue(BaseModel):
    code: CriticIssueCode
    message: str
    severity: CriticSeverity = "blocking"
    action: CriticAction = "accept"
    tool: str | None = None
    topic: str | None = None


class CriticResult(BaseModel):
    passed: bool
    issues: list[CriticIssue] = Field(default_factory=list)
    next_action: CriticAction = "accept"
    gap_query: str | None = None
    checked: list[str] = Field(default_factory=list)

    @property
    def blocking_issues(self) -> list[CriticIssue]:
        return [issue for issue in self.issues if issue.severity == "blocking"]
