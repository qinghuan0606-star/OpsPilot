"""Ops tools: structured output, typed 404s, argument validation, timeout, permissions."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from app.config.settings import get_settings
from app.core.enums import ToolRisk
from app.core.exceptions import (
    InvalidRequestError,
    PackageNotFoundError,
    ServiceNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
)
from app.ops.backend import MockBackend
from app.ops.fixtures import load_fixtures
from app.ops.hosts import HostRegistry
from app.schemas.agent import ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.ops_tools import (
    CheckRpmDependenciesTool,
    GetCpuMemoryTool,
    GetDiskUsageTool,
    GetRpmInfoTool,
    GetServiceLogsTool,
    GetServiceStatusTool,
    GetSystemInfoTool,
    RestartServiceTool,
)


def _stack(allowed=("lab-node-1", "lab-node-2")):
    hosts, fixtures = load_fixtures()
    registry = HostRegistry(hosts, allowed=list(allowed))
    backend = MockBackend(hosts, fixtures)
    settings = get_settings().model_copy(update={"ops_default_host": "lab-node-1"})
    return backend, registry, settings


def _ctx(host_id: str = "lab-node-1") -> ToolContext:
    return ToolContext(user_id="u1", session_id="s1", trace_id="t1", host_id=host_id)


@pytest.mark.asyncio
async def test_system_info_reports_simulated_open_euler() -> None:
    backend, hosts, settings = _stack()
    tool = GetSystemInfoTool(backend, hosts, settings)
    result = await tool.run({}, _ctx())
    assert result.success
    assert "oe2403" in result.output["kernel"]
    assert result.output["os_name"] == "openEuler"
    assert result.output["simulated"] == "true"
    assert result.output["evidence"]["locator"] == "inventory:lab-node-1"


@pytest.mark.asyncio
async def test_service_status_failed_nginx() -> None:
    backend, hosts, settings = _stack()
    tool = GetServiceStatusTool(backend, hosts, settings)
    result = await tool.run({"service": "nginx"}, _ctx())
    assert result.output["state"] == "failed"
    assert result.output["exit_code"] == 1
    assert result.output["restart_count"] == 3


@pytest.mark.asyncio
async def test_service_logs_carry_dlopen_error() -> None:
    backend, hosts, settings = _stack()
    tool = GetServiceLogsTool(backend, hosts, settings)
    result = await tool.run({"service": "nginx", "lines": 10}, _ctx())
    assert any("dlopen" in entry["msg"] for entry in result.output["entries"])
    assert result.output["source"] == "journal"


@pytest.mark.asyncio
async def test_unknown_package_and_service_are_typed_404() -> None:
    backend, hosts, settings = _stack()
    with pytest.raises(PackageNotFoundError):
        await GetRpmInfoTool(backend, hosts, settings).run({"package": "no-such-pkg"}, _ctx())
    with pytest.raises(ServiceNotFoundError):
        await GetServiceStatusTool(backend, hosts, settings).run({"service": "no-such"}, _ctx())


@pytest.mark.asyncio
async def test_shell_fragment_in_arguments_is_rejected() -> None:
    backend, hosts, settings = _stack()
    with pytest.raises(InvalidRequestError):
        await GetServiceStatusTool(backend, hosts, settings).run(
            {"service": "nginx; rm -rf /tmp"}, _ctx()
        )
    with pytest.raises(InvalidRequestError):
        await GetDiskUsageTool(backend, hosts, settings).run(
            {"paths": ["/; cat /etc/passwd"]}, _ctx()
        )


@pytest.mark.asyncio
async def test_rmp_dependency_issue_is_structured() -> None:
    backend, hosts, settings = _stack()
    result = await CheckRpmDependenciesTool(backend, hosts, settings).run(
        {"package": "nginx"}, _ctx()
    )
    assert result.output["missing"]
    assert result.output["repo_available"] is False
    assert result.output["stale_files"]


@pytest.mark.asyncio
async def test_disk_filter_and_cpu_top_n() -> None:
    backend, hosts, settings = _stack()
    disk = await GetDiskUsageTool(backend, hosts, settings).run({"paths": ["/var"]}, _ctx())
    assert [fs["mount"] for fs in disk.output["filesystems"]] == ["/var"]
    cpu = await GetCpuMemoryTool(backend, hosts, settings).run({"top_n": 1}, _ctx("lab-node-2"))
    assert len(cpu.output["top_processes"]) == 1


@pytest.mark.asyncio
async def test_host_outside_allow_list_is_denied() -> None:
    backend, hosts, settings = _stack(allowed=("lab-node-1",))
    with pytest.raises(ToolPermissionError):
        await GetSystemInfoTool(backend, hosts, settings).run({"host_id": "lab-node-2"}, _ctx())


@pytest.mark.asyncio
async def test_cross_host_retarget_is_denied() -> None:
    backend, hosts, settings = _stack()
    tool = GetSystemInfoTool(backend, hosts, settings)
    with pytest.raises(ToolPermissionError):
        await tool.run({"host_id": "lab-node-2"}, _ctx("lab-node-1"))


@pytest.mark.asyncio
async def test_write_tool_respects_feature_flag() -> None:
    backend, hosts, settings = _stack()
    disabled = settings.model_copy(update={"ops_enable_write_tools": False})
    with pytest.raises(ToolPermissionError):
        await RestartServiceTool(backend, hosts, disabled).run(
            {"service": "nginx", "reason": "验证修复后重启"}, _ctx()
        )
    enabled = settings.model_copy(update={"ops_enable_write_tools": True})
    result = await RestartServiceTool(backend, hosts, enabled).run(
        {"service": "nginx", "reason": "验证修复后重启"}, _ctx()
    )
    assert result.output["restart_attempted"] is True
    assert result.output["simulated"] == "true"
    assert result.output["note"].startswith("mock backend")


class _SlowInput(BaseModel):
    pass


class _SlowTool(Tool):
    name = "slow_tool"
    description = "sleeps"
    risk = ToolRisk.READ
    input_model = _SlowInput

    async def execute(self, parsed, context) -> ToolResult:
        await asyncio.sleep(0.2)
        return ToolResult(name=self.name, success=True)


@pytest.mark.asyncio
async def test_tool_timeout_is_enforced_by_scheduler_not_by_tool() -> None:
    tool = _SlowTool()
    ctx = ToolContext(user_id="u", session_id="s", trace_id="t", timeout_seconds=0.05)
    with pytest.raises(ToolTimeoutError):
        await tool.run({}, ctx)
