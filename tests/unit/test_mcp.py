"""MCP tools behind the same function-calling contract."""

import pytest

from app.mcp.adapter import merge_mcp_tools
from app.mcp.runtime import LOCAL_CATALOG, call_mcp_tool
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_local_mcp_executes_change_window() -> None:
    output = await call_mcp_tool(name="mcp_change_window", arguments={}, transport="local")
    assert output["windows"]
    assert output["approval_required"] is True
    assert output["source"] == "mcp_local"
    assert output["simulated"] is True


@pytest.mark.asyncio
async def test_mcp_proxy_is_function_calling_tool() -> None:
    registry = ToolRegistry()
    merge_mcp_tools(registry, list(LOCAL_CATALOG))
    tool = registry.get("mcp_oncall_roster")
    schema = tool.openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "mcp_oncall_roster"
    result = await tool.run({}, ToolContext(user_id="u", session_id="s", trace_id="t"))
    assert result.success is True
    assert result.output["escalation"] == "platform_owner"
