"""Registered inspection targets and per-operator host authorisation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.exceptions import HostNotFoundError, ToolPermissionError


class HostProfile(BaseModel):
    """A machine the ops tools may inspect. Nothing here is a real production host."""

    host_id: str
    hostname: str = ""
    os_name: str = ""
    os_version: str = ""
    kernel: str = ""
    arch: str = "x86_64"
    backend: str = "mock"
    labels: list[str] = Field(default_factory=list)
    note: str = ""


class HostRegistry:
    """Resolve host ids and enforce the allow-list before any tool call.

    The allow-list is the only authorisation model in this phase: an operator
    session may only touch hosts listed in ``ops_allowed_hosts``. Real per-user
    authorisation arrives with the authentication work (see docs/12-limitations.md).
    """

    def __init__(self, hosts: list[HostProfile], *, allowed: list[str] | None = None) -> None:
        self._hosts = {host.host_id: host for host in hosts}
        self._allowed = set(allowed) if allowed is not None else set(self._hosts)

    def host_ids(self) -> list[str]:
        """Allow-listed host ids, for health output and the console."""
        return [host.host_id for host in self.list_allowed()]

    def all(self) -> list[HostProfile]:
        return [self._hosts[host_id] for host_id in sorted(self._hosts)]

    def list_allowed(self) -> list[HostProfile]:
        return [host for host in self.all() if host.host_id in self._allowed]

    def resolve(self, host_id: str | None, *, default: str) -> HostProfile:
        resolved = (host_id or default or "").strip()
        if not resolved:
            raise HostNotFoundError("no host specified and no default host configured")
        if resolved not in self._hosts:
            raise HostNotFoundError(f"unknown host: {resolved}")
        if resolved not in self._allowed:
            raise ToolPermissionError(f"host {resolved} is not in the operator allow-list")
        return self._hosts[resolved]
