"""Dangerous operation detection for ops queries.

Two separate guarantees:
1. This layer refuses requests that ask the assistant to run destructive or
   privileged shell work at all.
2. The tool plane never accepts a command string, so even a model that ignores
   the refusal cannot turn text into execution.
"""

from __future__ import annotations

import re

from app.core.error_codes import ErrorCode
from app.core.exceptions import GuardrailError

_DANGEROUS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"rm\s+-[a-z]*r[a-z]*f?\s*(/|/usr|/var|/etc)\b", re.I),
        "recursive delete of system path",
    ),
    (re.compile(r"\bmkfs(\.\w+)?\b", re.I), "format a filesystem"),
    (re.compile(r"\bdd\s+if=.*\bof=/dev/", re.I | re.S), "raw write to a block device"),
    (
        re.compile(r"\b(shutdown|reboot|poweroff|halt|init\s+0)\b", re.I),
        "shutdown or reboot the host",
    ),
    (re.compile(r">\s*/etc/(passwd|shadow|sudoers)", re.I), "overwrite an authentication file"),
    (
        re.compile(r"\bchmod\s+[-+]?[0-7]*7[0-7][0-7]\s+(/|/usr|/etc)\b", re.I),
        "world-writable system path",
    ),
    (re.compile(r":\s*\(\s*\)\s*\{", re.I), "fork bomb"),
    (
        re.compile(r"\b(curl|wget)\b[\s\S]{0,200}\|\s*(ba)?sh\b", re.I),
        "pipe remote script into a shell",
    ),
    (re.compile(r"\b(useradd|usermod|passwd)\s+root\b", re.I), "modify the root account"),
    (re.compile(r"\bsudo\s+(rm|dd|mkfs|chmod\s+777)\b", re.I), "privileged destructive command"),
)

# Asking for these is refused even without an explicit command string.
_INTENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(帮我|给我|直接)(执行|运行|跑一下)\s*(这条|这个|如下)?\s*(命令|脚本|shell)", re.I
        ),
        "request to execute",
    ),
    (re.compile(r"(绕过|跳过|关闭)\s*(审批|确认|权限|审计)", re.I), "request to bypass approval"),
    (re.compile(r"(提权|拿到)\s*(root|管理员)权限", re.I), "privilege escalation request"),
    (re.compile(r"关闭\s*(防火墙|selinux)", re.I), "disable security controls"),
)


def detect_dangerous_operation(text: str) -> None:
    """Raise when the query itself is a destructive or privileged operation."""
    for pattern, reason in _DANGEROUS_PATTERNS:
        if pattern.search(text):
            raise GuardrailError(
                f"危险操作已被拦截：{reason}。请通过变更工单与人工审批流程处理。",
                ErrorCode.COMMAND_NOT_ALLOWED,
            )
    for pattern, reason in _INTENT_PATTERNS:
        if pattern.search(text):
            raise GuardrailError(
                f"危险操作已被拦截：{reason}。系统不会生成或执行任意 Shell 命令。",
                ErrorCode.COMMAND_NOT_ALLOWED,
            )
