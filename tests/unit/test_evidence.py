"""Unified evidence and citation derivation."""

from __future__ import annotations

from app.agents.nodes.generate import citations_from_evidence
from app.core.enums import DocumentCategory
from app.schemas.evidence import EvidenceKind, knowledge_evidence, tool_evidence
from app.schemas.retrieval import RetrievedChunk


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        document_id="doc-rpm",
        title="RPM 依赖冲突",
        content="nothing provides libGeoIP.so.1",
        score=0.9,
        rank=1,
        category=DocumentCategory.RPM_PACKAGE,
        metadata={"source_type": "self_written", "source_note": "自写"},
    )


def test_knowledge_evidence_keeps_provenance() -> None:
    item = knowledge_evidence(_chunk())
    assert item.evidence_id == "kb:c1"
    assert item.kind == EvidenceKind.KNOWLEDGE
    assert item.metadata["source_type"] == "self_written"


def test_tool_evidence_uses_tool_supplied_locator() -> None:
    item = tool_evidence(
        tool_name="get_service_status",
        step_id=3,
        output={
            "host": "lab-node-1",
            "evidence": {
                "title": "nginx failed",
                "locator": "systemctl:nginx@lab-node-1",
                "excerpt": "state=failed",
            },
        },
    )
    assert item.evidence_id == "tool:3:get_service_status"
    assert item.reference == "systemctl:nginx@lab-node-1"
    assert item.metadata["host"] == "lab-node-1"


def test_tool_evidence_summarises_when_tool_gives_no_excerpt() -> None:
    item = tool_evidence(tool_name="get_disk_usage", step_id=1, output={"host": "h", "use_pct": 90})
    assert "use_pct=90" in item.excerpt


def test_citations_include_tool_evidence_on_agent_path() -> None:
    evidence = [
        knowledge_evidence(_chunk()),
        tool_evidence(
            tool_name="get_service_status",
            step_id=2,
            output={"evidence": {"title": "nginx failed", "locator": "systemctl:nginx@lab-node-1"}},
        ),
    ]
    citations = citations_from_evidence(evidence, {"tool:2:get_service_status"})
    assert len(citations) == 1
    assert citations[0].kind == "tool"
    assert citations[0].locator == "systemctl:nginx@lab-node-1"
