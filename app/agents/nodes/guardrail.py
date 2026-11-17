"""Input guardrail node: injection, scope and dangerous-operation checks."""

from app.agents.state import AgentState
from app.core.enums import RetrievalStrategy
from app.core.exceptions import GuardrailError
from app.guardrails.boundary import assert_in_scope
from app.guardrails.injection import detect_prompt_injection
from app.guardrails.ops_safety import detect_dangerous_operation

_BLOCKED_MESSAGE = (
    "该请求被安全策略拦截：涉及危险命令、越权操作或提示词注入。"
    "我不会生成或执行任何 Shell 命令；如需变更请走工单与人工审批。"
)


async def guardrail_node(state: AgentState) -> dict:
    query = state["user_query"]
    try:
        detect_prompt_injection(query)
        detect_dangerous_operation(query)
        assert_in_scope(query)
    except GuardrailError as exc:
        return {
            "refused": True,
            "strategy": RetrievalStrategy.REFUSE,
            "final_answer": _BLOCKED_MESSAGE,
            "error": exc.error_code.value,
            "evidence": [],
        }
    return {}
