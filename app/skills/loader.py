"""Skill loading and matching for ops support."""

from __future__ import annotations

import json
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "definitions"

INTENT_TO_SKILL = {
    "package_rpm": "rpm_upgrade_failure",
    "service_ops": "service_failure_logs",
    "log_analysis": "elk_log_analysis",
    "fault_diagnosis": "service_failure_logs",
    "resource_check": "resource_check",
    "os_config": "os_baseline",
    "network_disk": "resource_check",
}


def load_skills() -> list[dict]:
    skills: list[dict] = []
    if not SKILLS_DIR.exists():
        return skills
    for path in sorted(SKILLS_DIR.glob("*.json")):
        skills.append(json.loads(path.read_text(encoding="utf-8")))
    return skills


def skill_by_name(name: str) -> dict | None:
    for skill in load_skills():
        if skill.get("name") == name:
            return skill
    return None


def _elk_requested(query: str) -> bool:
    lowered = query.lower()
    return any(
        cue in lowered
        for cue in (
            "elasticsearch",
            "elastic search",
            " elk",
            "elk ",
            "logstash",
            "kibana",
            "es 日志",
            "应用日志",
            "大量 error",
            "错误日志",
        )
    )


def match_skill(query: str, intent_label: str = "") -> dict | None:
    """Intent wins over generic trigger words.

    ``openEuler``/``麒麟`` appear in nearly every ops question; matching their
    triggers first would route RPM or service failures to ``os_baseline``.
    Trigger phrases remain a fallback when the intent has no skill mapping.

    A ``log_analysis`` intent is only ELK when the question actually asks for
    application/Elasticsearch logs; otherwise it stays on local service logs.
    """
    mapped = INTENT_TO_SKILL.get(intent_label)
    if mapped == "elk_log_analysis" and not _elk_requested(query):
        mapped = "service_failure_logs"
    if mapped:
        skill = skill_by_name(mapped)
        if skill:
            return skill
    for skill in load_skills():
        if any(trigger in query for trigger in skill.get("triggers", [])):
            return skill
    return None
