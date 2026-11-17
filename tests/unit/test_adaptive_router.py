"""Strategy routing on the ops domain."""

from app.agents.nodes.intent import rule_based_intent
from app.core.enums import IntentLabel, RetrievalStrategy
from app.retrieval.adaptive import needs_live_evidence, rule_based_complexity
from app.schemas.agent import IntentResult


def _intent(label: IntentLabel) -> IntentResult:
    return IntentResult(label=label, confidence=0.9, prompt_version="t", rationale="x")


def test_greeting_goes_direct() -> None:
    intent = rule_based_intent("你好")
    assert intent.label == IntentLabel.GREETING
    assert rule_based_complexity("你好", intent).strategy == RetrievalStrategy.DIRECT


def test_host_state_question_goes_agent() -> None:
    routed = rule_based_complexity(
        "查一下 lab-node-1 的 nginx 服务状态", _intent(IntentLabel.SERVICE_OPS)
    )
    assert routed.strategy == RetrievalStrategy.AGENT


def test_fault_report_is_multi_hop() -> None:
    routed = rule_based_complexity(
        "lab-node-1 上 nginx 升级后启动失败，帮我分析原因", _intent(IntentLabel.FAULT_DIAGNOSIS)
    )
    assert routed.strategy in {RetrievalStrategy.MULTI, RetrievalStrategy.AGENT}


def test_general_ops_howto_stays_single() -> None:
    routed = rule_based_complexity(
        "systemd 服务启动失败一般怎么排查？", _intent(IntentLabel.FAULT_DIAGNOSIS)
    )
    assert routed.strategy in {RetrievalStrategy.SINGLE, RetrievalStrategy.MULTI}


def test_conceptual_rpm_question_does_not_need_a_host() -> None:
    routed = rule_based_complexity(
        "rpm -q 和 rpm -V 有什么区别？", _intent(IntentLabel.PACKAGE_RPM)
    )
    assert routed.strategy == RetrievalStrategy.SINGLE
    assert needs_live_evidence("rpm -q 和 rpm -V 有什么区别？") is False


def test_explicit_bundle_question_is_multi() -> None:
    routed = rule_based_complexity(
        "nginx 升级失败，而且 systemd 起不来，日志还报依赖缺失，怎么处理",
        _intent(IntentLabel.FAULT_DIAGNOSIS),
    )
    assert routed.strategy == RetrievalStrategy.MULTI
