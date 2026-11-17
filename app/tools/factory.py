"""Tool registry composition for OpsPilot."""

from app.config.settings import Settings
from app.ops.backend import OpsBackend
from app.ops.hosts import HostRegistry
from app.retrieval.hybrid import HybridRetriever
from app.tools.ops_tools import (
    AggregateErrorLogsTool,
    CheckRpmDependenciesTool,
    GetCpuMemoryTool,
    GetDiskUsageTool,
    GetLogstashPipelineStatusTool,
    GetRpmInfoTool,
    GetServiceLogsTool,
    GetServiceStatusTool,
    GetSupervisorProgramConfigTool,
    GetSystemInfoTool,
    ListSupervisorProgramsTool,
    RestartServiceTool,
    SearchElasticsearchLogsTool,
)
from app.tools.registry import ToolRegistry
from app.tools.support_tools import EscalateToHumanTool, SearchKnowledgeTool


def build_tool_registry(
    retriever: HybridRetriever,
    backend: OpsBackend,
    hosts: HostRegistry,
    settings: Settings,
) -> ToolRegistry:
    """Register knowledge, the read-only ops tools and the optional write action.

    Read tools are always present. ``restart_service`` is registered only when
    ``ops_enable_write_tools`` is on: a disabled flag must not produce a
    confirmation prompt that could never execute. The tool re-checks the flag at
    execution time as the second gate.
    """
    registry = ToolRegistry()
    tools = [
        SearchKnowledgeTool(retriever),
        GetSystemInfoTool(backend, hosts, settings),
        GetCpuMemoryTool(backend, hosts, settings),
        GetDiskUsageTool(backend, hosts, settings),
        GetServiceStatusTool(backend, hosts, settings),
        GetServiceLogsTool(backend, hosts, settings),
        GetRpmInfoTool(backend, hosts, settings),
        CheckRpmDependenciesTool(backend, hosts, settings),
        ListSupervisorProgramsTool(backend, hosts, settings),
        GetSupervisorProgramConfigTool(backend, hosts, settings),
        SearchElasticsearchLogsTool(backend, hosts, settings),
        AggregateErrorLogsTool(backend, hosts, settings),
        GetLogstashPipelineStatusTool(backend, hosts, settings),
        EscalateToHumanTool(),
    ]
    if settings.ops_enable_write_tools:
        tools.append(RestartServiceTool(backend, hosts, settings))
    for tool in tools:
        registry.register(tool)
    return registry
