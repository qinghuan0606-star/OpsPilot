"""Diagnosis critic: pre-answer, deterministic, bounded corrections."""

from app.agents.nodes.critic import critic_node
from app.agents.state import AgentState
from app.config.settings import Settings
from app.core.enums import IntentLabel, RetrievalStrategy, ToolExecutionStatus
from app.schemas.agent import AgentPlan, IntentResult, PlanStep, ToolResult
from app.schemas.evidence import EvidenceItem, EvidenceKind


def _knowledge() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="kb:1",
        kind=EvidenceKind.KNOWLEDGE,
        source="RPM 依赖冲突",
        reference="1",
        title="RPM 依赖冲突",
        excerpt="检查 requires 与 conflicts",
    )


def _state(**overrides) -> AgentState:
    base = {
        "user_query": "nginx 服务启动失败，帮我排查原因",
        "strategy": RetrievalStrategy.AGENT,
        "intent": IntentResult(
            label=IntentLabel.FAULT_DIAGNOSIS,
            confidence=0.9,
            rationale="t",
            prompt_version="v",
        ),
        "evidence": [],
        "tool_results": [],
        "plan": None,
        "plan_fingerprint": None,
        "plan_history": [],
        "critic_round": 0,
        "retrieval_round": 0,
        "extra": {},
        "evidence_sufficient": True,
        "evidence_gaps": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def _settings() -> Settings:
    return Settings(app_env="testing", max_correction_rounds=2, max_evidence_hops=2)


def test_missing_target_requests_clarification_not_a_guess() -> None:
    result = critic_node(
        _state(extra={"missing_target": True, "missing_target_kind": "service"}), _settings()
    )
    critic = result["critic_result"]
    assert critic.next_action == "clarify"
    assert any(issue.code == "missing_target" for issue in critic.issues)
    assert result["critic_round"] == 0


def test_incomplete_plan_requests_missing_tool() -> None:
    plan = AgentPlan(
        steps=[
            PlanStep(
                step_id=1,
                goal="status",
                tool_name="get_service_status",
                arguments={"host_id": "lab-node-1", "service": "nginx"},
            )
        ],
        rationale="test",
    )
    result = critic_node(
        _state(
            plan=plan,
            evidence=[_knowledge()],
            tool_results=[
                ToolResult(
                    name="get_service_status",
                    success=True,
                    output={"service": "nginx", "state": "failed"},
                )
            ],
        ),
        _settings(),
    )
    critic = result["critic_result"]
    assert critic.next_action == "plan"
    assert any(
        issue.code == "missing_tool" and issue.tool == "get_service_logs" for issue in critic.issues
    )
    assert result["critic_round"] == 1


def test_correction_budget_exhaustion_accepts_with_gaps() -> None:
    plan = AgentPlan(
        steps=[
            PlanStep(
                step_id=1,
                goal="status",
                tool_name="get_service_status",
                arguments={"host_id": "lab-node-1", "service": "nginx"},
            ),
            PlanStep(
                step_id=2,
                goal="logs",
                tool_name="get_service_logs",
                arguments={"host_id": "lab-node-1", "service": "nginx", "lines": 50},
            ),
        ],
        rationale="test",
    )
    result = critic_node(
        _state(
            plan=plan,
            tool_results=[
                ToolResult(name="get_service_status", success=True, output={"state": "failed"}),
                ToolResult(name="get_service_logs", success=True, output={"entries": []}),
            ],
            evidence=[
                EvidenceItem(
                    evidence_id="tool:1",
                    kind=EvidenceKind.TOOL,
                    source="get_service_status",
                    reference="status",
                    title="status",
                )
            ],
            critic_round=2,
            retrieval_round=2,
        ),
        _settings(),
    )
    critic = result["critic_result"]
    assert critic.next_action == "accept"
    assert any(issue.code == "missing_knowledge" for issue in critic.issues)
    assert result["critic_round"] == 2


def test_fallback_is_a_warning_and_not_tool_evidence() -> None:
    plan = AgentPlan(
        steps=[
            PlanStep(
                step_id=1,
                goal="status",
                tool_name="get_service_status",
                arguments={"host_id": "lab-node-1", "service": "nginx"},
            )
        ],
        rationale="test",
    )
    fallback = ToolResult(
        name="search_knowledge",
        success=True,
        output={"fallback_from": "get_service_status", "chunks": []},
        status=ToolExecutionStatus.FALLBACK,
        requested_name="get_service_status",
        failure_kind="tool_execution_failed",
    )
    result = critic_node(
        _state(
            user_query="nginx 服务状态",
            plan=plan,
            evidence=[_knowledge()],
            tool_results=[fallback],
            critic_round=1,
        ),
        _settings(),
    )
    critic = result["critic_result"]
    codes = {issue.code for issue in critic.issues}
    assert "fallback_warning" in codes
    assert "tool_failed" in codes
    assert not any(
        issue.code == "missing_tool"
        and issue.action == "plan"
        and issue.tool == "get_service_status"
        for issue in critic.issues
    )


def test_plan_repeat_stops_the_loop() -> None:
    plan = AgentPlan(
        steps=[
            PlanStep(
                step_id=1,
                goal="status",
                tool_name="get_service_status",
                arguments={"host_id": "lab-node-1", "service": "nginx"},
            )
        ],
        rationale="test",
    )
    result = critic_node(
        _state(
            user_query="nginx 服务状态",
            plan=plan,
            plan_fingerprint="fp",
            plan_history=["fp", "fp"],
            evidence=[_knowledge()],
            tool_results=[ToolResult(name="search_knowledge", success=False, error="down")],
            critic_round=1,
        ),
        _settings(),
    )
    critic = result["critic_result"]
    assert critic.next_action == "accept"
    assert any(issue.code == "plan_repeat" for issue in critic.issues)


def test_service_and_package_state_do_not_cross_contaminate() -> None:
    """A failed nginx service and installed nginx RPM are different facts."""
    result = critic_node(
        _state(
            user_query="nginx 依赖冲突，帮我分析原因",
            plan=AgentPlan(
                steps=[
                    PlanStep(
                        step_id=1,
                        goal="rpm",
                        tool_name="get_rpm_info",
                        arguments={"host_id": "lab-node-1", "package": "nginx"},
                    ),
                    PlanStep(
                        step_id=2,
                        goal="dep",
                        tool_name="check_rpm_dependencies",
                        arguments={"host_id": "lab-node-1", "package": "nginx"},
                    ),
                    PlanStep(
                        step_id=3,
                        goal="status",
                        tool_name="get_service_status",
                        arguments={"host_id": "lab-node-1", "service": "nginx"},
                    ),
                    PlanStep(
                        step_id=4,
                        goal="logs",
                        tool_name="get_service_logs",
                        arguments={"host_id": "lab-node-1", "service": "nginx", "lines": 50},
                    ),
                ],
                rationale="test",
            ),
            evidence=[_knowledge()],
            tool_results=[
                ToolResult(
                    name="get_rpm_info",
                    success=True,
                    output={"name": "nginx", "state": "installed"},
                ),
                ToolResult(
                    name="check_rpm_dependencies",
                    success=True,
                    output={"package": "nginx", "missing": []},
                ),
                ToolResult(
                    name="get_service_status",
                    success=True,
                    output={"service": "nginx", "state": "failed"},
                ),
                ToolResult(name="get_service_logs", success=True, output={"entries": []}),
            ],
        ),
        _settings(),
    )
    critic = result["critic_result"]
    assert not any("同时出现多个状态" in issue.message for issue in critic.issues)


def test_supervisor_status_and_program_list_conflict_is_flagged() -> None:
    plan = AgentPlan(
        steps=[
            PlanStep(
                step_id=1,
                goal="status",
                tool_name="get_service_status",
                arguments={"host_id": "lab-node-1", "service": "app-worker"},
            ),
            PlanStep(
                step_id=2,
                goal="list",
                tool_name="list_supervisor_programs",
                arguments={"host_id": "lab-node-1"},
            ),
        ],
        rationale="test",
    )
    result = critic_node(
        _state(
            user_query="app-worker 被 Supervisor 反复重启",
            plan=plan,
            evidence=[_knowledge()],
            tool_results=[
                ToolResult(
                    name="get_service_status",
                    success=True,
                    output={"host": "lab-node-1", "service": "app-worker", "state": "failed"},
                ),
                ToolResult(
                    name="list_supervisor_programs",
                    success=True,
                    output={
                        "host": "lab-node-1",
                        "programs": [
                            {"program": "app-worker", "service": "app-worker", "state": "active"}
                        ],
                    },
                ),
                ToolResult(name="get_service_logs", success=True, output={"entries": []}),
            ],
        ),
        _settings(),
    )
    assert any(issue.code == "evidence_conflict" for issue in result["critic_result"].issues)


def test_supervisor_config_program_mismatch_is_flagged() -> None:
    plan = AgentPlan(
        steps=[
            PlanStep(
                step_id=1,
                goal="status",
                tool_name="get_service_status",
                arguments={"host_id": "lab-node-1", "service": "nginx"},
            ),
            PlanStep(
                step_id=2,
                goal="config",
                tool_name="get_supervisor_program_config",
                arguments={"host_id": "lab-node-1", "program": "app-worker"},
            ),
        ],
        rationale="test",
    )
    result = critic_node(
        _state(
            user_query="nginx 服务启动失败",
            plan=plan,
            evidence=[_knowledge()],
            tool_results=[
                ToolResult(
                    name="get_service_status",
                    success=True,
                    output={"host": "lab-node-1", "service": "nginx", "state": "failed"},
                ),
                ToolResult(name="get_service_logs", success=True, output={"entries": []}),
            ],
        ),
        _settings(),
    )
    assert any(issue.code == "target_mismatch" for issue in result["critic_result"].issues)
