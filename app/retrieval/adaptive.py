"""Adaptive-RAG complexity routing for ops queries.

Paper mapping (Jeong et al., ACL 2024):
- simple      -> DIRECT (no retrieval) or REFUSE
- single_hop  -> SINGLE (one-shot hybrid retrieval)
- multi_hop   -> MULTI  (Self-RAG iterative retrieval, may escalate to tools)
- tool needs  -> AGENT  (planner + ops tools, optional retrieval)

LLM classifier is preferred. Rule fallback keeps the system testable and
available when the model is down.
"""

from __future__ import annotations

import re

from app.core.constants import PROMPT_VERSION_COMPLEXITY
from app.core.enums import IntentLabel, QueryComplexity, RetrievalStrategy
from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.complexity import COMPLEXITY_SYSTEM, COMPLEXITY_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import parse_model
from app.schemas.agent import ComplexityResult, IntentResult

# Multi-hop cues: a question that chains causes, conditions or two systems.
_MULTI_HOP_CUES = (
    "同时",
    "并且",
    "另外",
    "以及",
    "如果",
    "但是",
    "然后",
    "既",
    "又",
    "升级后",
    "升级了",
    "之后",
    " besides",
    "and then",
)
# Live-evidence cues: the answer depends on the state of a machine, not on docs.
_LIVE_CUES = (
    "这台",
    "该主机",
    "服务器",
    "主机",
    "我的",
    "现场",
    "当前",
    "现在",
    "服务状态",
    "启动失败",
    "起不来",
    "日志",
    "journal",
    "rpm -q",
    "版本是多少",
    "装的是",
    "占用",
    "使用率",
    "负载",
    "磁盘满",
    "cpu",
    "内存",
    "nginx",
    "sshd",
    "docker",
    "supervisor",
    "app-worker",
    "频繁退出",
    "反复重启",
    "自动重启",
    "一直重启",
    "退出码",
    "exited",
    "systemctl",
    "服务状态",
)
_HOST_ID = re.compile(r"\b(lab-node-\d+|host-\d+)\b", re.IGNORECASE)
_PACKAGE = re.compile(r"\b([a-z][a-z0-9+._-]{1,30})\b")
_POLICY_CUES = ("规范", "最佳实践", "标准", "手册", "怎么配置", "原理", "是什么")
# Explicitly conceptual questions must not be forced onto the tool plane, even
# when they mention a command name like `rpm -q`.
_CONCEPT_CUES = (
    "有什么区别",
    "区别",
    "是什么意思",
    "怎么用",
    "如何用",
    "含义",
    "原理",
    "解释",
    "介绍",
)


def needs_live_evidence(query: str) -> bool:
    """True when the question needs a host lookup rather than only documents."""
    text = query.lower()
    if _HOST_ID.search(query):
        return True
    if any(cue in text for cue in _CONCEPT_CUES) and not any(
        cue in text for cue in ("状态", "占用", "使用率", "起不来", "启动失败", "报错")
    ):
        return False
    return any(cue in text for cue in _LIVE_CUES)


def rule_based_complexity(query: str, intent: IntentResult) -> ComplexityResult:
    text = query.strip()
    lowered = text.lower()
    if intent.label == IntentLabel.OUT_OF_SCOPE:
        return ComplexityResult(
            complexity=QueryComplexity.OUT_OF_SCOPE,
            strategy=RetrievalStrategy.REFUSE,
            confidence=0.95,
            rationale="intent_out_of_scope",
        )
    if intent.label in {IntentLabel.GREETING, IntentLabel.CHITCHAT}:
        return ComplexityResult(
            complexity=QueryComplexity.SIMPLE,
            strategy=RetrievalStrategy.DIRECT,
            confidence=0.9,
            rationale="social_or_greeting",
        )
    live = needs_live_evidence(text)
    multi = any(cue in lowered for cue in _MULTI_HOP_CUES)
    if live and intent.label == IntentLabel.FAULT_DIAGNOSIS:
        # A live fault question starts as MULTI so documents are gathered first;
        # once evidence is assessed the MULTI branch may still escalate to tools.
        return ComplexityResult(
            complexity=QueryComplexity.MULTI_HOP,
            strategy=RetrievalStrategy.MULTI,
            confidence=0.82,
            rationale="fault_with_live_evidence",
        )
    if live:
        return ComplexityResult(
            complexity=QueryComplexity.TOOL_REQUIRED,
            strategy=RetrievalStrategy.AGENT,
            confidence=0.78,
            rationale="live_state_question",
        )
    if multi:
        return ComplexityResult(
            complexity=QueryComplexity.MULTI_HOP,
            strategy=RetrievalStrategy.MULTI,
            confidence=0.7,
            rationale="multi_hop_cue",
        )
    return ComplexityResult(
        complexity=QueryComplexity.SINGLE_HOP,
        strategy=RetrievalStrategy.SINGLE,
        confidence=0.68,
        rationale="single_hop_knowledge",
    )


class AdaptiveRouter:
    def __init__(
        self,
        llm: LLMProvider,
        *,
        system_prompt: str = COMPLEXITY_SYSTEM,
        prompt_version: str = PROMPT_VERSION_COMPLEXITY,
    ) -> None:
        self._llm = llm
        self._system_prompt = system_prompt
        self._prompt_version = prompt_version

    async def route(self, query: str, intent: IntentResult) -> ComplexityResult:
        fallback = rule_based_complexity(query, intent)
        if isinstance(self._llm, OfflineLLMProvider):
            return self._guard(query, fallback)
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": COMPLEXITY_USER.format(
                            query=query,
                            intent=intent.label.value,
                            prompt_version=self._prompt_version,
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            return self._guard(query, parse_model(response.content, ComplexityResult))
        except (LLMProviderError, LLMOutputError):
            return self._guard(query, fallback)

    def _guard(self, query: str, result: ComplexityResult) -> ComplexityResult:
        """Post-guards keep routing safe even if the model picks something silly.

        A pure knowledge question must not silently become an AGENT run that
        touches a machine, and a question about live state must not be answered
        from documents alone.
        """
        if not needs_live_evidence(query) and result.strategy == RetrievalStrategy.AGENT:
            return ComplexityResult(
                complexity=QueryComplexity.SINGLE_HOP,
                strategy=RetrievalStrategy.SINGLE,
                confidence=0.75,
                rationale="guard:knowledge_only_no_agent",
            )
        if needs_live_evidence(query) and result.strategy in {
            RetrievalStrategy.SINGLE,
            RetrievalStrategy.DIRECT,
        }:
            return ComplexityResult(
                complexity=QueryComplexity.TOOL_REQUIRED,
                strategy=RetrievalStrategy.AGENT,
                confidence=0.8,
                rationale="guard:live_state_requires_agent",
            )
        return result
