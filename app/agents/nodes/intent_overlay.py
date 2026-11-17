"""High-precision lexical overlay applied after the LLM intent classifier.

The LLM stays primary. Overlay only fires on phrases that are stable in ops
Chinese and that confuse neighbouring labels: a "service won't start" report is
a fault diagnosis, not a generic knowledge question; a package version question
is not a service question.
"""

from __future__ import annotations

import re

from app.core.enums import IntentLabel

_GREETING_ONLY = re.compile(
    r"^(你好|您好|hi|hello|早上好|在吗)(，在吗)?[!！。.~]*$",
    re.IGNORECASE,
)

_HANDOFF = ("转人工", "人工客服", "找运维", "值班", "升级工单")
_JAILBREAK = ("ignore previous", "jailbreak", "系统提示词", "绕过审批")
_OOS = ("写作业", "股市", "炒股", "医疗诊断", "写诗", "翻译论文", "总统")
_SECURITY = ("selinux", "防火墙", "sudo", "权限", "umask", "chmod", "chown", "审计")
_RPM = ("rpm", "yum", "dnf", "依赖", "软件包", "安装包", "升级包", "repo")
_SERVICE = (
    "systemd",
    "systemctl",
    "supervisor",
    "服务",
    "service",
    "unit",
    "nginx",
    "sshd",
    "docker",
    "mysqld",
    "redis",
)
_LOG = ("日志", "journal", "报错", "error", "崩溃", "traceback", "dlopen")
_RESOURCE = ("cpu", "内存", "磁盘", "负载", "iowait", "swap", "oom")
_FAULT = ("启动失败", "起不来", "fail", "failed", "异常", "排查", "诊断", "定位")
_NET_DISK = ("网卡", "dns", "路由", "端口", "丢包", "ping", "磁盘满")


def high_precision_intent(query: str) -> IntentLabel | None:
    text = query.strip()
    if not text:
        return None
    lowered = text.lower()

    if any(token in lowered for token in _JAILBREAK) or any(token in text for token in _OOS):
        return IntentLabel.OUT_OF_SCOPE
    if any(token in text for token in _HANDOFF):
        return IntentLabel.HUMAN_HANDOFF
    if _GREETING_ONLY.match(text) or _GREETING_ONLY.match(lowered):
        return IntentLabel.GREETING
    if any(token in lowered for token in _SECURITY):
        return IntentLabel.SECURITY_PERM
    # "How do I read error logs" is a log question, not a diagnosis report.
    if any(token in lowered for token in _LOG) and any(
        token in text for token in ("怎么", "如何", "是什么", "区别", "用法")
    ):
        return IntentLabel.LOG_ANALYSIS
    # A "failed to start" report that also mentions packages is still a fault
    # diagnosis first: the package is evidence, not the question.
    if any(token in lowered for token in _FAULT) and any(
        token in lowered for token in _SERVICE + _RPM + _LOG
    ):
        return IntentLabel.FAULT_DIAGNOSIS
    if any(token in lowered for token in _LOG):
        return IntentLabel.LOG_ANALYSIS
    if any(token in lowered for token in _RPM):
        return IntentLabel.PACKAGE_RPM
    if any(token in lowered for token in _SERVICE):
        return IntentLabel.SERVICE_OPS
    if any(token in lowered for token in _NET_DISK):
        return IntentLabel.NETWORK_DISK
    if any(token in lowered for token in _RESOURCE):
        return IntentLabel.RESOURCE_CHECK
    return None


def apply_intent_overlay(query: str, label: IntentLabel) -> tuple[IntentLabel, str]:
    """Return possibly-corrected label plus an audit note when overlay fires."""
    override = high_precision_intent(query)
    if override is None or override == label:
        return label, ""
    return override, f"overlay:{label.value}->{override.value}"
