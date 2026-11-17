"""Local and remote MCP backends behind the same call_tool contract."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.exceptions import ToolExecutionError

LOCAL_CATALOG: list[dict[str, str]] = [
    {
        "name": "mcp_change_window",
        "description": (
            "查询运维变更窗口与冻结期（模拟组织策略，不代表真实排班系统）。"
            "何时用：能否在今晚重启服务、是否处于变更冻结、需要走审批的场景。"
            "何时不用：服务当前状态用 get_service_status；重启动作本身用 restart_service。"
            "无需必填参数。返回 windows[]、freeze_period、approval_required。"
        ),
        "transport": "local",
    },
    {
        "name": "mcp_oncall_roster",
        "description": (
            "查询当班运维值班队列与升级路径（模拟数据）。"
            "何时用：需要转人工、找值班负责人、确认升级到哪一级。"
            "何时不用：普通知识问答、只读查询不需要转人工。"
            "无需必填参数。返回 primary/secondary/escalation 三个队列。"
        ),
        "transport": "local",
    },
]

_LOCAL_HANDLERS: dict[str, dict[str, Any]] = {
    "mcp_change_window": {
        "windows": ["工作日 20:00-23:00", "周六 09:00-12:00"],
        "freeze_period": "季度末最后 3 个工作日",
        "approval_required": True,
        "simulated": True,
        "source": "mcp_local",
    },
    "mcp_oncall_roster": {
        "primary": "ops_shift_l1",
        "secondary": "ops_shift_l2",
        "escalation": "platform_owner",
        "simulated": True,
        "source": "mcp_local",
    },
}


async def call_mcp_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    transport: str,
    endpoint: str = "",
) -> dict[str, Any]:
    if transport == "local":
        if name not in _LOCAL_HANDLERS:
            raise ToolExecutionError(f"unknown local MCP tool: {name}")
        return {**_LOCAL_HANDLERS[name], "arguments": arguments}
    if not endpoint:
        raise ToolExecutionError(f"remote MCP tool {name} has no endpoint")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                endpoint,
                json={"name": name, "arguments": arguments},
                headers={"content-type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise ToolExecutionError(f"remote MCP transport error: {name}") from exc
    if response.status_code >= 400:
        raise ToolExecutionError(f"remote MCP HTTP {response.status_code}")
    body = response.json()
    if not isinstance(body, dict):
        raise ToolExecutionError("remote MCP returned non-object JSON")
    return body
