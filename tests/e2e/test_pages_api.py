"""Contracts used by the six console pages (3.5)."""

from fastapi.testclient import TestClient

from app.config.settings import clear_settings_cache
from app.main import create_app


def _client() -> TestClient:
    clear_settings_cache()
    return TestClient(create_app())


def test_knowledge_detail_matches_indexed_chunks() -> None:
    with _client() as client:
        listing = client.get("/api/v1/ops/knowledge/documents").json()
        assert listing["count"] >= 29
        document = next(d for d in listing["documents"] if d["chunk_count"] > 0)
        detail = client.get(f"/api/v1/ops/knowledge/documents/{document['document_id']}").json()
    assert detail["found"] is True
    assert detail["document"]["document_id"] == document["document_id"]
    assert len(detail["chunks"]) == document["chunk_count"]
    assert all(chunk["content"].strip() for chunk in detail["chunks"])


def test_tool_catalog_exposes_policy_fields() -> None:
    with _client() as client:
        body = client.get("/api/v1/ops/tools").json()
        admin_body = client.get("/api/v1/admin/tools").json()
    assert body["write_tools_enabled"] is False
    assert body["count"] == len(body["tools"])
    assert body["count"] == admin_body["count"]
    for tool in body["tools"]:
        assert tool["enabled"] is True
        assert isinstance(tool["read_only"], bool)
        assert isinstance(tool["requires_confirmation"], bool)
        assert tool["source"] == "tool_registry"


def test_monitoring_overview_exposes_error_logs_and_processes() -> None:
    with _client() as client:
        body = client.get("/api/v1/ops/hosts/lab-node-1/overview").json()
    assert body["inode_use_pct"] is not None
    assert body["resources"]["cpu"]["load_5"] is not None
    assert body["top_processes"]
    assert body["error_logs"]["service"]
    assert body["error_logs"]["source"] in {"journal", "supervisor", "unavailable"}
    assert body["simulated"] is True


def test_chat_plan_and_critic_are_persisted_for_trace_page() -> None:
    with _client() as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "帮我查一下 lab-node-1 的 nginx 服务状态和最近错误日志",
                "user_id": "u_pages",
            },
        ).json()
        trace_id = response["trace_id"]
        detail = client.get(f"/api/v1/diagnoses/{trace_id}").json()
        listing = client.get("/api/v1/diagnoses?limit=5").json()["items"]

    assert response["execution_status"] == "completed"
    assert response["plan"] and response["plan"]["steps"]
    assert response["critic_result"] is not None
    assert response["critic_round"] >= 1
    assert detail["found"] is True
    assert detail["item"]["execution_status"] == "completed"
    assert detail["item"]["plan"]["steps"]
    assert detail["item"]["critic_result"] is not None
    assert listing[0]["trace_id"] == trace_id


def test_direct_answer_has_no_empty_plan_object() -> None:
    with _client() as client:
        response = client.post(
            "/api/v1/chat", json={"message": "你好", "user_id": "u_pages"}
        ).json()
        detail = client.get(f"/api/v1/diagnoses/{response['trace_id']}").json()
    assert response["execution_status"] == "completed"
    assert detail["found"] is True
    assert detail["item"]["plan"] is None
    assert detail["item"]["critic_result"] is None
