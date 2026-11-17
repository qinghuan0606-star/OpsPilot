"""Rule-based intent and deterministic offline answers (no key needed)."""

import pytest

from app.agents.nodes.generate import generate_node
from app.agents.nodes.intent import IntentClassifier, rule_based_intent
from app.core.enums import IntentLabel, RetrievalStrategy
from app.providers.fake import OfflineLLMProvider
from app.schemas.retrieval import RetrievedChunk


def test_greeting_prefix_does_not_hide_fault_intent() -> None:
    intent = rule_based_intent("你好，我这边 nginx 升级后起不来了")
    assert intent.label != IntentLabel.GREETING
    assert intent.label == IntentLabel.FAULT_DIAGNOSIS


@pytest.mark.asyncio
async def test_offline_classifier_uses_rules_not_fake_json() -> None:
    intent = await IntentClassifier(OfflineLLMProvider()).classify(
        "journalctl 怎么查指定服务的日志？"
    )
    assert intent.label in {IntentLabel.LOG_ANALYSIS, IntentLabel.SERVICE_OPS}


@pytest.mark.asyncio
async def test_offline_answer_quotes_evidence_instead_of_test_json() -> None:
    chunk = RetrievedChunk(
        chunk_id="chunk-1",
        document_id="doc-rpm",
        title="RPM 依赖冲突",
        content="nothing provides libGeoIP.so.1 needed by nginx-mod-http-geoip",
        score=1.0,
        rank=1,
    )
    result = await generate_node(
        {
            "user_query": "nginx 升级后报依赖缺失怎么处理？",
            "strategy": RetrievalStrategy.MULTI,
            "retrieved_chunks": [chunk],
            "evidence": [],
        },
        OfflineLLMProvider(),
    )
    assert "libGeoIP" in result["final_answer"]
    assert '"label"' not in result["final_answer"]
    assert result["citations"][0].chunk_id == "chunk-1"
