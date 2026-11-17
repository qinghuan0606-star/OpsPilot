"""Unified evidence model.

Knowledge retrieval and tool execution used to live in two disconnected shapes:
`retrieved_chunks` and `tool_results`. That made AGENT-path citations impossible
because the answer only ever looked at chunks. Every piece of support for an answer
is now an :class:`EvidenceItem`, whatever produced it, and citations are derived
from that single list.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.retrieval import RetrievedChunk


class EvidenceKind(str, Enum):
    KNOWLEDGE = "knowledge"
    TOOL = "tool"


class EvidenceItem(BaseModel):
    """One citable unit of support for an answer.

    Attributes:
        evidence_id: Stable id, `kb:<chunk_id>` or `tool:<step>:<name>`.
        kind: Which pipeline produced it.
        source: Human-facing producer: document title or tool name.
        reference: Machine locator: chunk_id, or a tool-side locator such as
            `journal:nginx.service@lab-node-1`.
        title: Heading shown in the citation list.
        excerpt: Short excerpt included in the prompt and the citation panel.
        score: Retrieval score when the item came from the retriever.
        metadata: Free-form tags, e.g. category / source_type / host.
    """

    evidence_id: str
    kind: EvidenceKind = EvidenceKind.KNOWLEDGE
    source: str
    reference: str
    title: str
    excerpt: str = ""
    score: float | None = None
    rank: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    def prompt_block(self) -> str:
        """Render this item for the answer/faithfulness prompts."""
        return f"[{self.evidence_id}] ({self.kind.value}) {self.title}\n{self.excerpt}"


def knowledge_evidence(chunk: RetrievedChunk) -> EvidenceItem:
    metadata = {
        "category": chunk.category.value,
        "document_id": chunk.document_id,
        **{k: str(v) for k, v in chunk.metadata.items()},
    }
    return EvidenceItem(
        evidence_id=f"kb:{chunk.chunk_id}",
        kind=EvidenceKind.KNOWLEDGE,
        source=chunk.title,
        reference=chunk.chunk_id,
        title=chunk.title,
        excerpt=chunk.content[:400],
        score=chunk.score,
        rank=chunk.rank,
        metadata=metadata,
    )


def tool_evidence(
    *,
    tool_name: str,
    step_id: int,
    output: dict[str, Any],
    fallback_from: str | None = None,
) -> EvidenceItem:
    """Build evidence from a tool's structured output.

    Tools put a small `evidence` block in their output with `title`, `locator`
    and `excerpt`; everything else in the payload is data, not a citation.
    """
    block = output.get("evidence") if isinstance(output, dict) else None
    block = block if isinstance(block, dict) else {}
    host = str(output.get("host") or block.get("host") or "") if isinstance(output, dict) else ""
    locator = str(block.get("locator") or "")
    if not locator:
        locator = f"tool:{tool_name}" + (f"@{host}" if host else "")
    title = str(block.get("title") or tool_name)
    excerpt = str(block.get("excerpt") or "")
    if not excerpt:
        excerpt = _summarise_output(output)
    metadata = {"tool": tool_name, "step_id": str(step_id)}
    if host:
        metadata["host"] = host
    if fallback_from:
        metadata["fallback_from"] = fallback_from
    return EvidenceItem(
        evidence_id=f"tool:{step_id}:{tool_name}",
        kind=EvidenceKind.TOOL,
        source=tool_name,
        reference=locator,
        title=title,
        excerpt=excerpt[:400],
        metadata=metadata,
    )


def _summarise_output(output: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in output.items():
        if key == "evidence":
            continue
        if isinstance(value, str | int | float | bool):
            parts.append(f"{key}={value}")
        elif isinstance(value, list) and value and isinstance(value[0], str | int | float):
            parts.append(f"{key}[{len(value)}]")
    return "; ".join(parts)[:400]
