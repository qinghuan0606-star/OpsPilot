"""Phase 3.4 ops tools: ELK, Supervisor, extended service fields, RPM not-found."""

from __future__ import annotations

import pytest

from app.config.settings import get_settings
from app.core.exceptions import (
    BackendUnavailableError,
    InvalidRequestError,
    PackageNotFoundError,
    ServiceNotFoundError,
)
from app.ops.backend import MockBackend
from app.ops.fixtures import load_fixtures
from app.ops.hosts import HostRegistry
from app.tools.base import ToolContext
from app.tools.ops_tools import (
    AggregateErrorLogsTool,
    CheckRpmDependenciesTool,
    GetLogstashPipelineStatusTool,
    GetRpmInfoTool,
    GetServiceLogsTool,
    GetServiceStatusTool,
    GetSupervisorProgramConfigTool,
    ListSupervisorProgramsTool,
    SearchElasticsearchLogsTool,
)


def _stack():
    hosts, fixtures = load_fixtures()
    backend = MockBackend(hosts, fixtures)
    registry = HostRegistry(hosts, allowed=["lab-node-1", "lab-node-2"])
    settings = get_settings().model_copy(update={"ops_default_host": "lab-node-1"})
    return backend, registry, settings


def _ctx(host_id: str = "lab-node-1") -> ToolContext:
    return ToolContext(user_id="u1", session_id="s1", trace_id="t1", host_id=host_id)


@pytest.mark.asyncio
async def test_services_status_exposes_phase_34_correlation_fields() -> None:
    backend, hosts, settings = _stack()
    result = await GetServiceStatusTool(backend, hosts, settings).run({"service": "nginx"}, _ctx())
    output = result.output
    assert output["enabled"] is True
    assert output["exit_code"] == 1
    assert output["restart_count"] == len(output["restart_events"]) == 3
    assert output["last_failure_at"] == "2026-11-16T09:12:03+08:00"
    assert output["stop_reason"]
    assert output["exec_start"] == "/usr/sbin/nginx -c /etc/nginx/nginx.conf"
    assert "unit_config" in output


@pytest.mark.asyncio
async def test_supervisor_service_evidence_is_not_mislabelled_as_systemctl() -> None:
    backend, hosts, settings = _stack()
    status = await GetServiceStatusTool(backend, hosts, settings).run(
        {"service": "app-worker"}, _ctx()
    )
    logs = await GetServiceLogsTool(backend, hosts, settings).run({"service": "app-worker"}, _ctx())
    assert status.output["manager"] == "supervisor"
    assert status.output["evidence"]["locator"].startswith("supervisorctl:")
    assert logs.output["source"] == "supervisor"
    assert logs.output["evidence"]["locator"].startswith("supervisor-log:")


@pytest.mark.asyncio
async def test_supervisor_program_list_and_config_are_correlated() -> None:
    backend, hosts, settings = _stack()
    listed = await ListSupervisorProgramsTool(backend, hosts, settings).run({}, _ctx())
    assert listed.output["total"] == 1
    program = listed.output["programs"][0]
    assert program["program"] == "app-worker"
    assert program["state"] == "failed"
    assert program["restart_count"] == 5

    config = await GetSupervisorProgramConfigTool(backend, hosts, settings).run(
        {"program": "app-worker"}, _ctx()
    )
    assert config.output["autostart"] is True
    assert config.output["autorestart"] == "unexpected"
    assert config.output["startsecs"] == 2
    assert config.output["startretries"] == 5
    assert len(config.output["restart_events"]) == config.output["restart_count"] == 5
    assert config.output["evidence"]["locator"].startswith("supervisor:")


@pytest.mark.asyncio
async def test_unknown_supervisor_program_is_service_not_found() -> None:
    backend, hosts, settings = _stack()
    with pytest.raises(ServiceNotFoundError):
        await GetSupervisorProgramConfigTool(backend, hosts, settings).run(
            {"program": "not-managed"}, _ctx()
        )


@pytest.mark.asyncio
async def test_elasticsearch_search_filters_level_and_time() -> None:
    backend, hosts, settings = _stack()
    result = await SearchElasticsearchLogsTool(backend, hosts, settings).run(
        {
            "service": "app-worker",
            "level": "ERROR",
            "since": "2026-11-16T09:15:00+08:00",
            "limit": 10,
        },
        _ctx(),
    )
    output = result.output
    assert output["source"] == "elasticsearch"
    assert output["matched_indices"] == ["app-logs-2026.11.16"]
    assert output["total"] == 2
    assert all(entry["level"] == "ERROR" for entry in output["entries"])
    assert all(entry["timestamp"] >= "2026-11-16T09:15:00+08:00" for entry in output["entries"])
    assert output["evidence"]["locator"].startswith("es:")


@pytest.mark.asyncio
async def test_error_aggregation_returns_error_type_counts() -> None:
    backend, hosts, settings = _stack()
    result = await AggregateErrorLogsTool(backend, hosts, settings).run(
        {"group_by": "error_type", "limit": 10}, _ctx()
    )
    output = result.output
    assert output["total_errors"] == 11
    counts = {bucket["key"]: bucket["count"] for bucket in output["buckets"]}
    assert counts["DatabaseConnectionError"] == 4
    assert counts["NginxModuleLoadError"] == 2
    assert counts["SupervisorStartFailure"] == 2
    assert output["evidence"]["locator"].startswith("es-agg:")


@pytest.mark.asyncio
async def test_logstash_pipeline_supports_running_failed_and_unavailable() -> None:
    backend, hosts, settings = _stack()
    result = await GetLogstashPipelineStatusTool(backend, hosts, settings).run({}, _ctx())
    states = {pipeline["pipeline_id"]: pipeline["state"] for pipeline in result.output["pipelines"]}
    assert states == {"main": "running", "nginx-error": "failed", "archive": "unavailable"}

    failed = await GetLogstashPipelineStatusTool(backend, hosts, settings).run(
        {"pipeline_id": "nginx-error"}, _ctx()
    )
    assert failed.output["summary"]["failed"] == 1
    assert failed.output["pipelines"][0]["queue_events"] == 12800


@pytest.mark.asyncio
async def test_elasticsearch_unavailable_is_typed_backend_error() -> None:
    backend, hosts, settings = _stack()
    with pytest.raises(BackendUnavailableError):
        await SearchElasticsearchLogsTool(backend, hosts, settings).run({}, _ctx("lab-node-2"))
    with pytest.raises(BackendUnavailableError):
        await GetLogstashPipelineStatusTool(backend, hosts, settings).run({}, _ctx("lab-node-2"))


@pytest.mark.asyncio
async def test_unknown_rpm_package_is_not_a_successful_empty_dependency_result() -> None:
    backend, hosts, settings = _stack()
    with pytest.raises(PackageNotFoundError):
        await CheckRpmDependenciesTool(backend, hosts, settings).run(
            {"package": "no-such-pkg"}, _ctx()
        )


@pytest.mark.asyncio
async def test_elasticsearch_index_pattern_rejects_query_like_input() -> None:
    backend, hosts, settings = _stack()
    with pytest.raises(InvalidRequestError):
        await SearchElasticsearchLogsTool(backend, hosts, settings).run(
            {"index_pattern": "app-logs-*; GET /_search"}, _ctx()
        )


@pytest.mark.asyncio
async def test_service_logs_time_level_and_keyword_filters() -> None:
    backend, hosts, settings = _stack()
    urgent = await GetServiceLogsTool(backend, hosts, settings).run(
        {"service": "nginx", "level_min": "err", "lines": 20}, _ctx()
    )
    assert len(urgent.output["entries"]) == 4
    assert all(entry["level"] in {"emerg", "err"} for entry in urgent.output["entries"])

    keyword = await GetServiceLogsTool(backend, hosts, settings).run(
        {"service": "nginx", "keyword": "dlopen", "lines": 20}, _ctx()
    )
    assert len(keyword.output["entries"]) == 1
    assert "libGeoIP.so.1" in keyword.output["entries"][0]["msg"]


@pytest.mark.asyncio
async def test_service_status_restart_events_and_logs_have_matching_timestamps() -> None:
    backend, hosts, settings = _stack()
    status = await GetServiceStatusTool(backend, hosts, settings).run({"service": "nginx"}, _ctx())
    logs = await GetServiceLogsTool(backend, hosts, settings).run(
        {"service": "nginx", "lines": 20}, _ctx()
    )
    last_event = status.output["restart_events"][-1]
    assert last_event["at"] == status.output["last_failure_at"]
    assert any(entry["ts"] == last_event["at"] for entry in logs.output["entries"])
    assert status.output["restart_count"] == len(status.output["restart_events"])


@pytest.mark.asyncio
async def test_rpm_info_exposes_repo_and_available_versions() -> None:
    backend, hosts, settings = _stack()
    info = await GetRpmInfoTool(backend, hosts, settings).run({"package": "nginx"}, _ctx())
    assert info.output["repo_id"] == "openEuler-24.03-LTS-SP1"
    assert info.output["repo_url"].startswith("https://repo.openeuler.org/")
    assert "1.26.1-1.oe2403" in info.output["available_versions"]

    deps = await CheckRpmDependenciesTool(backend, hosts, settings).run(
        {"package": "nginx"}, _ctx()
    )
    assert deps.output["package_state"] == "installed"
