"""Tool registry and dispatch."""

from __future__ import annotations

from app.core.exceptions import InvalidRequestError
from app.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise InvalidRequestError(f"unknown tool: {name}") from exc

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def openai_tools(self) -> list[dict]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def describe(self) -> list[dict]:
        """Tool metadata for the ops console tools page."""
        return [
            {
                "name": tool.name,
                "risk": tool.risk.value,
                "description": tool.description,
                "parameters": tool.input_model.model_json_schema(),
                "enabled": True,
                "read_only": tool.risk.value == "read",
                "requires_confirmation": tool.risk.value in {"write", "destructive"},
                "source": "tool_registry",
            }
            for tool in self._tools.values()
        ]
