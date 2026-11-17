import pytest

from app.agents.nodes.faithfulness import self_correct_answer
from app.guardrails.hallucination import FaithfulnessChecker
from app.providers.base import LLMResponse
from app.schemas.common import TokenUsage
from app.schemas.retrieval import RetrievedChunk


class _SequenceLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def ping(self) -> bool:
        return True

    async def generate(self, messages, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            content = '{"answer":"依赖缺失的软件包需补齐","citation_ids":[]}'
        else:
            content = '{"supported":true,"hallucinated_spans":[],"rationale":"ok"}'
        return LLMResponse(content=content, usage=TokenUsage(total_tokens=4), model="fake")


@pytest.mark.asyncio
async def test_self_correct_rewrites_unsupported_answer() -> None:
    llm = _SequenceLLM()
    checker = FaithfulnessChecker(llm)
    chunk = RetrievedChunk(
        chunk_id="c1",
        document_id="rpm_dependency_conflict_0",
        title="RPM 依赖冲突",
        content="升级后若提示 missing libGeoIP.so.1，需安装对应模块包。",
        score=1.0,
        rank=1,
        source="bm25",
    )
    from app.guardrails.hallucination import FaithfulnessResult

    first = FaithfulnessResult(
        supported=False, hallucinated_spans=["直接重启就能好"], rationale="unsupported"
    )
    answer, judged, corrected = await self_correct_answer(
        llm=llm,
        checker=checker,
        query="nginx 起不来，报缺 libGeoIP",
        answer="直接重启就能好",
        chunks=[chunk],
        evidence_text="- [kb:c1] RPM 依赖冲突：missing libGeoIP.so.1",
        tool_results_text="",
        first_result=first,
    )
    assert corrected is True
    assert judged.supported is True
    assert "libGeoIP" in answer or "依赖" in answer
