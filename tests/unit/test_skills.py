"""Ops skills: one skill, matched by trigger phrase or intent."""

from app.skills.loader import load_skills, match_skill


def test_ops_skills_are_installed() -> None:
    names = {skill["name"] for skill in load_skills()}
    assert names == {
        "rpm_upgrade_failure",
        "service_failure_logs",
        "resource_check",
        "os_baseline",
        "elk_log_analysis",
    }


def test_match_skill_by_trigger() -> None:
    skill = match_skill("nginx 升级后启动失败，日志报 dlopen", "fault_diagnosis")
    assert skill is not None
    assert skill["name"] in {"rpm_upgrade_failure", "service_failure_logs"}
    assert "get_service_logs" in skill["tools"]


def test_match_skill_by_intent_when_no_trigger() -> None:
    skill = match_skill("帮我看看这台机器的情况", "resource_check")
    assert skill is not None
    assert skill["name"] == "resource_check"
    assert "get_cpu_memory" in skill["tools"]


def test_no_skill_for_out_of_scope() -> None:
    assert match_skill("今天天气真好", "out_of_scope") is None


def test_log_analysis_intent_routes_to_elk_only_for_elk_questions() -> None:
    elk = match_skill("最近应用日志出现大量 ERROR，帮我分析原因", "log_analysis")
    assert elk is not None
    assert elk["name"] == "elk_log_analysis"
    assert "search_elasticsearch_logs" in elk["tools"]

    local = match_skill("nginx 日志报错了，帮我看看", "log_analysis")
    assert local is not None
    assert local["name"] == "service_failure_logs"
