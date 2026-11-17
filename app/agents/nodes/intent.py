"""Intent classification for ops support: rule fast path plus LLM classifier."""

from __future__ import annotations

import re

from app.agents.nodes.intent_overlay import apply_intent_overlay
from app.core.constants import PROMPT_VERSION_INTENT
from app.core.enums import IntentLabel
from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.intent import INTENT_SYSTEM, INTENT_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import parse_model
from app.schemas.agent import IntentResult

# Ordered so the most specific ops domain wins over a generic keyword.
_KEYWORD_RULES: list[tuple[tuple[str, ...], IntentLabel]] = [
    (("转人工", "人工客服", "找运维值班", "升级工单"), IntentLabel.HUMAN_HANDOFF),
    (("你好", "您好", "hi", "hello"), IntentLabel.GREETING),
    (("rpm", "yum", "dnf", "依赖冲突", "软件包", "安装包", "repo"), IntentLabel.PACKAGE_RPM),
    (
        (
            "systemd",
            "systemctl",
            "supervisor",
            "服务启动",
            "启动失败",
            "service 状态",
            "频繁退出",
            "反复重启",
            "自动重启",
            "退出码",
        ),
        IntentLabel.SERVICE_OPS,
    ),
    (("journalctl", "日志", "log", "报错", "error", "traceback", "崩溃"), IntentLabel.LOG_ANALYSIS),
    (("cpu", "内存", "磁盘", "负载", "iowait", "oom", "swap"), IntentLabel.RESOURCE_CHECK),
    (
        ("防火墙", "selinux", "权限", "sudo", "用户组", "chmod", "chown", "umask"),
        IntentLabel.SECURITY_PERM,
    ),
    (
        ("网络", "网卡", "dns", "路由", "端口", "ss -", "ping", "丢包", "连通"),
        IntentLabel.NETWORK_DISK,
    ),
    (
        ("内核", "发行版", "版本", "ostree", "systemd 配置", "sysctl", "limits.conf", "grub"),
        IntentLabel.OS_CONFIG,
    ),
    (("命令", "常用命令", "怎么用", "man ", "参数说明", "shell"), IntentLabel.LINUX_BASICS),
    (("故障", "诊断", "排查", "起不来", "定位原因"), IntentLabel.FAULT_DIAGNOSIS),
]

_OOS = ("写作业", "股市", "炒股", "医疗诊断", "总统", "写诗", "写小说", "翻译论文")


def rule_based_intent(query: str) -> IntentResult:
    lowered = query.lower()
    for keywords, label in _KEYWORD_RULES:
        if label == IntentLabel.GREETING:
            matched = bool(
                re.fullmatch(r"(?:你好|您好|hi|hello)[!！。．.\s]*", query.strip(), re.I)
            )
        else:
            matched = any(keyword.lower() in lowered for keyword in keywords)
        if matched:
            return IntentResult(
                label=label,
                confidence=0.72,
                rationale=f"keyword:{keywords[0]}",
                prompt_version="intent_rules_v2",
            )
    if any(word in query for word in _OOS):
        return IntentResult(
            label=IntentLabel.OUT_OF_SCOPE,
            confidence=0.9,
            rationale="blocked_topic",
            prompt_version="intent_rules_v2",
        )
    # Default to general Linux knowledge: it is the broadest safe ops bucket.
    return IntentResult(
        label=IntentLabel.LINUX_BASICS,
        confidence=0.55,
        rationale="default_linux_basics",
        prompt_version="intent_rules_v2",
    )


class IntentClassifier:
    def __init__(
        self,
        llm: LLMProvider,
        *,
        system_prompt: str = INTENT_SYSTEM,
        prompt_version: str = PROMPT_VERSION_INTENT,
        apply_overlay: bool = True,
    ) -> None:
        self._llm = llm
        self._system_prompt = system_prompt
        self._prompt_version = prompt_version
        self._apply_overlay = apply_overlay

    async def classify(self, query: str) -> IntentResult:
        fallback = rule_based_intent(query)
        if isinstance(self._llm, OfflineLLMProvider):
            return self._maybe_overlay(query, fallback)
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": INTENT_USER.format(
                            query=query, prompt_version=self._prompt_version
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            parsed = parse_model(response.content, IntentResult)
            if not parsed.prompt_version:
                parsed.prompt_version = self._prompt_version
            return self._maybe_overlay(query, parsed)
        except (LLMProviderError, LLMOutputError):
            return self._maybe_overlay(query, fallback)

    def _maybe_overlay(self, query: str, parsed: IntentResult) -> IntentResult:
        if not self._apply_overlay:
            return parsed
        label, overlay_note = apply_intent_overlay(query, parsed.label)
        if overlay_note:
            parsed.label = label
            parsed.rationale = f"{parsed.rationale};{overlay_note}"
            parsed.confidence = max(parsed.confidence, 0.93)
        return parsed
