"""Tool registry composition for the ops plane."""

from app.config.settings import get_settings
from app.ops.backend import MockBackend
from app.ops.fixtures import load_fixtures
from app.ops.hosts import HostRegistry
from app.tools.factory import build_tool_registry

_READ_OPS_TOOLS = {
    "get_system_info",
    "get_cpu_memory",
    "get_disk_usage",
    "get_service_status",
    "get_service_logs",
    "get_rpm_info",
    "check_rpm_dependencies",
    "list_supervisor_programs",
    "get_supervisor_program_config",
    "search_elasticsearch_logs",
    "aggregate_error_logs",
    "get_logstash_pipeline_status",
}
_SUPPORT_TOOLS = {"search_knowledge", "escalate_to_human"}


class _Retriever:
    async def retrieve(self, query, *, top_k):
        return []


def test_registry_contains_the_required_ops_tools() -> None:
    settings = get_settings().model_copy(update={"ops_enable_write_tools": False})
    hosts, fixtures = load_fixtures()
    registry = build_tool_registry(
        _Retriever(),  # type: ignore[arg-type]
        MockBackend(hosts, fixtures),
        HostRegistry(hosts, allowed=["lab-node-1", "lab-node-2"]),
        settings,
    )
    names = set(registry.names())
    assert names == _READ_OPS_TOOLS | _SUPPORT_TOOLS
    assert "restart_service" not in names


def test_write_tool_only_registered_when_enabled() -> None:
    settings = get_settings().model_copy(update={"ops_enable_write_tools": True})
    hosts, fixtures = load_fixtures()
    registry = build_tool_registry(
        _Retriever(),  # type: ignore[arg-type]
        MockBackend(hosts, fixtures),
        HostRegistry(hosts, allowed=["lab-node-1"]),
        settings,
    )
    assert "restart_service" in registry.names()


def test_describe_exposes_risk_and_json_schema() -> None:
    settings = get_settings().model_copy(update={"ops_enable_write_tools": True})
    hosts, fixtures = load_fixtures()
    registry = build_tool_registry(
        _Retriever(),  # type: ignore[arg-type]
        MockBackend(hosts, fixtures),
        HostRegistry(hosts, allowed=["lab-node-1"]),
        settings,
    )
    described = {item["name"]: item for item in registry.describe()}
    assert described["restart_service"]["risk"] == "destructive"
    assert described["get_service_status"]["risk"] == "read"
    assert described["get_service_status"]["parameters"]["type"] == "object"
