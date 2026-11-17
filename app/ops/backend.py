"""Execution backends behind one read-only ops interface.

The interface is deliberately capability-scoped: there is no `run(command)`.
A tool can only ask for a named inspection, so a model can never smuggle an
arbitrary shell command into the inspection plane.
"""

from __future__ import annotations

import fnmatch
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.core.enums import PackageState, ServiceState
from app.core.exceptions import BackendUnavailableError
from app.ops.hosts import HostProfile

_LOCAL_TZ = timezone(timedelta(hours=8))
_LEVEL_ORDER = {
    "debug": 0,
    "info": 1,
    "notice": 2,
    "warn": 3,
    "warning": 3,
    "err": 4,
    "error": 4,
    "crit": 5,
    "critical": 5,
    "alert": 6,
    "emerg": 7,
    "emergency": 7,
    "fatal": 7,
}
_LEVEL_ALIASES = {
    "warning": "warn",
    "error": "err",
    "critical": "crit",
    "emergency": "emerg",
    "fatal": "emerg",
}


def _parse_ts(value: str | None) -> datetime | None:
    """Parse the ISO timestamps used by fixtures; naive values mean Asia/Shanghai."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_LOCAL_TZ)
    return parsed


def _normalise_level(value: str | None) -> str | None:
    if not value:
        return None
    lowered = str(value).strip().lower()
    return _LEVEL_ALIASES.get(lowered, lowered)


def _level_matches(actual: str | None, requested: str | None) -> bool:
    if not requested:
        return True
    normal = _normalise_level(requested)
    if normal == "err":
        return _normalise_level(actual) in {"err", "crit", "alert", "emerg"}
    return _normalise_level(actual) == normal


def _level_at_least(actual: str | None, minimum: str | None) -> bool:
    if not minimum:
        return True
    actual_rank = _LEVEL_ORDER.get(_normalise_level(actual) or "", -1)
    minimum_rank = _LEVEL_ORDER.get(_normalise_level(minimum) or "", 99)
    return actual_rank >= minimum_rank


class OpsBackend(Protocol):
    name: str

    def hosts(self) -> list[HostProfile]: ...

    async def system_info(self, host_id: str) -> dict[str, Any]: ...

    async def cpu_memory(self, host_id: str, top_n: int) -> dict[str, Any]: ...

    async def disk_usage(self, host_id: str, paths: list[str] | None) -> dict[str, Any]: ...

    async def service_status(
        self, host_id: str, service: str, manager: str | None
    ) -> dict[str, Any]: ...

    async def service_logs(
        self,
        host_id: str,
        service: str,
        lines: int,
        since: str | None,
        until: str | None,
        level: str | None,
        level_min: str | None,
        keyword: str | None,
    ) -> dict[str, Any]: ...

    async def rpm_info(self, host_id: str, package: str) -> dict[str, Any]: ...

    async def rpm_dependencies(self, host_id: str, package: str) -> dict[str, Any]: ...

    async def supervisor_programs(self, host_id: str) -> dict[str, Any]: ...

    async def supervisor_program_config(self, host_id: str, program: str) -> dict[str, Any]: ...

    async def elasticsearch_logs(
        self,
        host_id: str,
        *,
        index_pattern: str,
        service: str | None,
        level: str | None,
        query: str | None,
        since: str | None,
        until: str | None,
        limit: int,
        sort: str,
    ) -> dict[str, Any]: ...

    async def aggregate_error_logs(
        self,
        host_id: str,
        *,
        index_pattern: str,
        service: str | None,
        level: str | None,
        query: str | None,
        since: str | None,
        until: str | None,
        group_by: str,
        interval: str,
        limit: int,
    ) -> dict[str, Any]: ...

    async def logstash_pipeline_status(
        self, host_id: str, pipeline_id: str | None
    ) -> dict[str, Any]: ...

    async def restart_service(
        self, host_id: str, service: str, reason: str, operator: str
    ) -> dict[str, Any]: ...

    async def service_catalog(self, host_id: str) -> list[dict[str, Any]]: ...

    async def package_catalog(self, host_id: str) -> list[dict[str, Any]]: ...


class LocalBackend:
    """Reserved: read-only inspection of the machine running this API.

    Not implemented in phase 2 on purpose. Implementing it means deciding
    privilege, command allow-listing and audit policy for a real host; that
    belongs with the deployment phase, not the domain migration phase.
    """

    name = "local"

    def __init__(self, hosts: list[HostProfile]) -> None:
        self._hosts = hosts

    def hosts(self) -> list[HostProfile]:
        return self._hosts

    def _todo(self, what: str) -> BackendUnavailableError:
        return BackendUnavailableError(
            f"local backend is reserved but not implemented in phase 2 ({what}); "
            "set OPS_TOOL_BACKEND=mock"
        )

    async def system_info(self, host_id: str) -> dict[str, Any]:
        raise self._todo("system_info")

    async def cpu_memory(self, host_id: str, top_n: int) -> dict[str, Any]:
        raise self._todo("cpu_memory")

    async def disk_usage(self, host_id: str, paths: list[str] | None) -> dict[str, Any]:
        raise self._todo("disk_usage")

    async def service_status(
        self, host_id: str, service: str, manager: str | None
    ) -> dict[str, Any]:
        raise self._todo("service_status")

    async def service_logs(
        self,
        host_id: str,
        service: str,
        lines: int,
        since: str | None,
        until: str | None,
        level: str | None,
        level_min: str | None,
        keyword: str | None,
    ) -> dict[str, Any]:
        raise self._todo("service_logs")

    async def rpm_info(self, host_id: str, package: str) -> dict[str, Any]:
        raise self._todo("rpm_info")

    async def rpm_dependencies(self, host_id: str, package: str) -> dict[str, Any]:
        raise self._todo("rpm_dependencies")

    async def supervisor_programs(self, host_id: str) -> dict[str, Any]:
        raise self._todo("supervisor_programs")

    async def supervisor_program_config(self, host_id: str, program: str) -> dict[str, Any]:
        raise self._todo("supervisor_program_config")

    async def elasticsearch_logs(
        self,
        host_id: str,
        *,
        index_pattern: str,
        service: str | None,
        level: str | None,
        query: str | None,
        since: str | None,
        until: str | None,
        limit: int,
        sort: str,
    ) -> dict[str, Any]:
        raise self._todo("elasticsearch_logs")

    async def aggregate_error_logs(
        self,
        host_id: str,
        *,
        index_pattern: str,
        service: str | None,
        level: str | None,
        query: str | None,
        since: str | None,
        until: str | None,
        group_by: str,
        interval: str,
        limit: int,
    ) -> dict[str, Any]:
        raise self._todo("aggregate_error_logs")

    async def logstash_pipeline_status(
        self, host_id: str, pipeline_id: str | None
    ) -> dict[str, Any]:
        raise self._todo("logstash_pipeline_status")

    async def restart_service(
        self, host_id: str, service: str, reason: str, operator: str
    ) -> dict[str, Any]:
        raise self._todo("restart_service")

    async def service_catalog(self, host_id: str) -> list[dict[str, Any]]:
        raise self._todo("service_catalog")

    async def package_catalog(self, host_id: str) -> list[dict[str, Any]]:
        raise self._todo("package_catalog")


class SshBackend(LocalBackend):
    """Reserved: remote inspection over SSH.

    TODO(phase 4+): implement with a read-only forced-command wrapper, per-host
    credentials from a secret store, and an explicit command allow-list.
    """

    name = "ssh"


class MockBackend:
    """Reads immutable fixtures. Every payload is simulated lab data."""

    name = "mock"

    def __init__(self, hosts: list[HostProfile], fixtures: dict[str, dict[str, Any]]) -> None:
        self._hosts = hosts
        self._fixtures = fixtures

    def hosts(self) -> list[HostProfile]:
        return self._hosts

    def _host(self, host_id: str) -> dict[str, Any]:
        data = self._fixtures.get(host_id)
        if data is None:
            raise BackendUnavailableError(f"no mock fixture for host {host_id}")
        return data

    def _simulation_note(self, host_id: str) -> dict[str, str]:
        return {"simulated": "true", "host": host_id, "data_source": "mock fixture"}

    async def system_info(self, host_id: str) -> dict[str, Any]:
        data = self._host(host_id)
        os_info = data.get("os", {})
        return {
            "host": host_id,
            "hostname": data.get("hostname", host_id),
            "os_name": os_info.get("name", ""),
            "os_version": os_info.get("version", ""),
            "kernel": os_info.get("kernel", ""),
            "arch": os_info.get("arch", "x86_64"),
            "vendor": os_info.get("vendor", ""),
            "uptime": data.get("uptime", ""),
            "evidence": {
                "title": f"{os_info.get('name', '')} {os_info.get('version', '')} / kernel {os_info.get('kernel', '')}",
                "locator": f"inventory:{host_id}",
                "excerpt": (
                    f"os-release: {os_info.get('name','')} {os_info.get('version','')}; "
                    f"kernel: {os_info.get('kernel','')}; arch: {os_info.get('arch','')}"
                ),
            },
            **self._simulation_note(host_id),
        }

    async def cpu_memory(self, host_id: str, top_n: int) -> dict[str, Any]:
        data = self._host(host_id)
        resources = data.get("resources", {})
        cpu = resources.get("cpu", {})
        memory = resources.get("memory", {})
        procs = (resources.get("top_processes") or [])[: max(1, top_n)]
        return {
            "host": host_id,
            "cpu": {
                "cores": cpu.get("cores"),
                "load_1": cpu.get("load_1"),
                "load_5": cpu.get("load_5"),
                "load_15": cpu.get("load_15"),
                "usage_pct": cpu.get("usage_pct"),
                "iowait_pct": cpu.get("iowait_pct"),
            },
            "memory": {
                "total_kb": memory.get("total_kb"),
                "available_kb": memory.get("available_kb"),
                "usage_pct": memory.get("usage_pct"),
                "swap_used_kb": memory.get("swap_used_kb"),
            },
            "top_processes": procs,
            "evidence": {
                "title": f"CPU {cpu.get('usage_pct')}% / MEM {memory.get('usage_pct')}% @ {host_id}",
                "locator": f"proc:{host_id}",
                "excerpt": (
                    f"load(1/5/15)={cpu.get('load_1')}/{cpu.get('load_5')}/{cpu.get('load_15')}; "
                    f"cpu={cpu.get('usage_pct')}%; mem_avail={memory.get('available_kb')}kB"
                ),
            },
            **self._simulation_note(host_id),
        }

    async def disk_usage(self, host_id: str, paths: list[str] | None) -> dict[str, Any]:
        data = self._host(host_id)
        filesystems = data.get("disks", [])
        if paths:
            wanted = [p for p in paths if p]
            filesystems = [
                fs for fs in filesystems if any(fs.get("mount", "").startswith(p) for p in wanted)
            ]
        worst = max(
            (fs.get("use_pct") or 0 for fs in filesystems),
            default=0,
        )
        return {
            "host": host_id,
            "filesystems": filesystems,
            "inode_use_pct": data.get("inode_use_pct"),
            "evidence": {
                "title": f"disk worst mount {worst}% @ {host_id}",
                "locator": f"df:{host_id}",
                "excerpt": "; ".join(
                    f"{fs.get('mount')}={fs.get('use_pct')}% ({fs.get('avail_kb')}kB avail)"
                    for fs in filesystems
                ),
            },
            **self._simulation_note(host_id),
        }

    async def service_status(
        self, host_id: str, service: str, manager: str | None
    ) -> dict[str, Any]:
        data = self._host(host_id)
        services = data.get("services", {})
        record = services.get(service)
        if record is None:
            raise OpsNotFound(f"service {service} not found on {host_id}")
        actual_manager = record.get("manager", "systemd")
        if manager and actual_manager != manager:
            raise OpsNotFound(f"service {service} is managed by {actual_manager}, not {manager}")
        state = record.get("state", ServiceState.UNKNOWN.value)
        program: dict[str, Any] = {}
        if actual_manager == "supervisor":
            programs = (data.get("supervisor") or {}).get("programs", {})
            program = programs.get(service) or next(
                (
                    config
                    for config in programs.values()
                    if isinstance(config, dict) and config.get("service") == service
                ),
                {},
            )
        config = program.get("config") or record.get("unit_config") or {}
        return {
            "host": host_id,
            "service": service,
            "manager": actual_manager,
            "state": state,
            "enabled": record.get("enabled", program.get("autostart")),
            "since": record.get("since", ""),
            "last_start_at": record.get("last_start_at", ""),
            "last_failure_at": record.get("last_failure_at", ""),
            "pid": record.get("pid"),
            "exit_code": record.get("exit_code"),
            "restart_count": record.get("restart_count", 0),
            "restart_events": record.get("restart_events", []),
            "unit_path": record.get("unit_path", program.get("config_path", "")),
            "last_error": record.get("last_error", ""),
            "stop_reason": record.get("stop_reason", ""),
            "exec_start": record.get("exec_start", program.get("command", "")),
            "restart_policy": record.get(
                "restart_policy", "on-failure" if program.get("autorestart") else ""
            ),
            "unit_config": config,
            "evidence": self._service_status_evidence(
                host_id, service, actual_manager, state, record, program
            ),
            **self._simulation_note(host_id),
        }

    def _service_status_evidence(
        self,
        host_id: str,
        service: str,
        manager: str,
        state: str,
        record: dict[str, Any],
        program: dict[str, Any],
    ) -> dict[str, str]:
        if manager == "supervisor":
            return {
                "title": f"supervisor program {service} state={state} @ {host_id}",
                "locator": f"supervisorctl:{service}@{host_id}",
                "excerpt": (
                    f"state={state}; pid={record.get('pid')}; exit_code={record.get('exit_code')}; "
                    f"restart_count={record.get('restart_count', 0)}; "
                    f"autorestart={program.get('autorestart')}; "
                    f"config={record.get('unit_path', program.get('config_path', ''))}"
                ),
            }
        return {
            "title": f"{service}.service state={state} @ {host_id}",
            "locator": f"systemctl:{service}@{host_id}",
            "excerpt": (
                f"ActiveState={state}; Result={record.get('result', 'exit-code')}; "
                f"ExecMainStatus={record.get('exit_code')}; "
                f"enabled={record.get('enabled')}; {record.get('last_error', '')}".strip()
            ),
        }

    async def service_logs(
        self,
        host_id: str,
        service: str,
        lines: int,
        since: str | None,
        until: str | None,
        level: str | None,
        level_min: str | None,
        keyword: str | None,
    ) -> dict[str, Any]:
        data = self._host(host_id)
        service_record = (data.get("services") or {}).get(service) or {}
        logs = (data.get("logs") or {}).get(service)
        if logs is None:
            raise OpsNotFound(f"no logs for {service} on {host_id}")
        entries = list(logs)
        if level:
            entries = [e for e in entries if _level_matches(e.get("level"), level)]
        if level_min:
            entries = [e for e in entries if _level_at_least(e.get("level"), level_min)]
        since_dt = _parse_ts(since)
        until_dt = _parse_ts(until)
        if since_dt:
            entries = [
                e for e in entries if (ts := _parse_ts(e.get("ts"))) is not None and ts >= since_dt
            ]
        if until_dt:
            entries = [
                e for e in entries if (ts := _parse_ts(e.get("ts"))) is not None and ts <= until_dt
            ]
        if keyword:
            needle = keyword.lower()
            entries = [
                e
                for e in entries
                if needle
                in " ".join(
                    str(e.get(key, "")) for key in ("msg", "level", "unit", "error_type")
                ).lower()
            ]
        truncated = len(entries) > lines
        entries = entries[-max(1, lines) :]
        manager = service_record.get("manager", "systemd")
        source = "supervisor" if manager == "supervisor" else "journal"
        locator = (
            f"supervisor-log:{service}@{host_id}"
            if manager == "supervisor"
            else f"journal:{service}@{host_id}"
        )
        return {
            "host": host_id,
            "service": service,
            "manager": manager,
            "entries": entries,
            "truncated": truncated,
            "source": source,
            "filters": {
                "since": since,
                "until": until,
                "level": level,
                "level_min": level_min,
                "keyword": keyword,
            },
            "evidence": {
                "title": f"{source} {service} tail ({len(entries)} lines) @ {host_id}",
                "locator": locator,
                "excerpt": "\n".join(
                    f"{e.get('ts','')} {e.get('level','')} {e.get('msg','')}" for e in entries[-3:]
                ),
            },
            **self._simulation_note(host_id),
        }

    async def rpm_info(self, host_id: str, package: str) -> dict[str, Any]:
        data = self._host(host_id)
        for record in data.get("packages", []):
            if record.get("name") == package:
                return {
                    "host": host_id,
                    "name": package,
                    "epoch": record.get("epoch", "0"),
                    "version": record.get("version", ""),
                    "release": record.get("release", ""),
                    "arch": record.get("arch", "x86_64"),
                    "state": record.get("state", PackageState.INSTALLED.value),
                    "license": record.get("license", ""),
                    "vendor": record.get("vendor", ""),
                    "repo_id": record.get("repo_id", ""),
                    "repo_url": record.get("repo_url", ""),
                    "available_versions": record.get("available_versions", []),
                    "install_time": record.get("install_time", ""),
                    "size_kb": record.get("size_kb"),
                    "requires": record.get("requires", []),
                    "provides": record.get("provides", []),
                    "evidence": {
                        "title": f"rpm {package}-{record.get('version', '')}-{record.get('release', '')} @ {host_id}",
                        "locator": f"rpm:{package}@{host_id}",
                        "excerpt": (
                            f"{package}-{record.get('epoch','0')}:{record.get('version','')}-"
                            f"{record.get('release','')}.{record.get('arch','')}; "
                            f"install_time={record.get('install_time','')}"
                        ),
                    },
                    **self._simulation_note(host_id),
                }
        raise OpsNotFound(f"package {package} not installed on {host_id}")

    async def rpm_dependencies(self, host_id: str, package: str) -> dict[str, Any]:
        data = self._host(host_id)
        packages = {record.get("name"): record for record in data.get("packages", [])}
        issues_by_package = data.get("dependency_issues") or {}
        if package not in packages and package not in issues_by_package:
            raise OpsNotFound(f"package {package} not found on {host_id}")
        issues = issues_by_package.get(package) or {}
        installed = set(packages)
        return {
            "host": host_id,
            "package": package,
            "package_state": (packages.get(package) or {}).get("state", "not_installed"),
            "missing": issues.get("missing", []),
            "conflicts": issues.get("conflicts", []),
            "satisfied": issues.get("satisfied", []),
            "broken_by": issues.get("broken_by", []),
            "stale_files": issues.get("stale_files", []),
            "repo_available": issues.get("repo_available"),
            "installed_related": self._related_packages(package, installed),
            "note": issues.get("note", ""),
            "evidence": {
                "title": f"dependency check {package} @ {host_id}",
                "locator": f"rpmdep:{package}@{host_id}",
                "excerpt": (
                    f"missing={issues.get('missing', [])}; broken_by={issues.get('broken_by', [])}; "
                    f"stale_files={issues.get('stale_files', [])}"
                ),
            },
            **self._simulation_note(host_id),
        }

    @staticmethod
    def _related_packages(package: str, installed: set[str]) -> list[str]:
        """Exact package or a package in the same hyphenated family, not arbitrary substring."""
        related = {
            name
            for name in installed
            if name == package or name.startswith(f"{package}-") or package.startswith(f"{name}-")
        }
        return sorted(related)

    async def supervisor_programs(self, host_id: str) -> dict[str, Any]:
        data = self._host(host_id)
        programs = (data.get("supervisor") or {}).get("programs", {})
        services = data.get("services", {})
        items: list[dict[str, Any]] = []
        for name, config in sorted(programs.items()):
            status = services.get(config.get("service", name)) or {}
            items.append(
                {
                    "program": name,
                    "service": config.get("service", name),
                    "state": status.get("state", "unknown"),
                    "pid": status.get("pid"),
                    "exit_code": status.get("exit_code"),
                    "restart_count": status.get("restart_count", 0),
                    "enabled": status.get("enabled", config.get("autostart")),
                    "autostart": config.get("autostart"),
                    "autorestart": config.get("autorestart"),
                    "startsecs": config.get("startsecs"),
                    "startretries": config.get("startretries"),
                    "config_path": config.get("config_path", ""),
                }
            )
        return {
            "host": host_id,
            "programs": items,
            "total": len(items),
            "source": "supervisorctl",
            "note": ("" if items else "当前 Mock 主机没有登记 Supervisor 托管程序"),
            "evidence": {
                "title": f"supervisorctl status ({len(items)} programs) @ {host_id}",
                "locator": f"supervisorctl:status@{host_id}",
                "excerpt": "; ".join(f"{item['program']}={item['state']}" for item in items),
            },
            **self._simulation_note(host_id),
        }

    async def supervisor_program_config(self, host_id: str, program: str) -> dict[str, Any]:
        data = self._host(host_id)
        configs = (data.get("supervisor") or {}).get("programs", {})
        config = configs.get(program)
        if config is None:
            raise OpsNotFound(f"supervisor program {program} not found on {host_id}")
        service = config.get("service", program)
        status = (data.get("services") or {}).get(service) or {}
        public_config = {
            key: value
            for key, value in config.items()
            if key
            in {
                "command",
                "directory",
                "user",
                "autostart",
                "autorestart",
                "startsecs",
                "startretries",
                "stopwaitsecs",
                "stdout_logfile",
                "stderr_logfile",
            }
        }
        return {
            "host": host_id,
            "program": program,
            "manager": "supervisor",
            "state": status.get("state", "unknown"),
            "config_path": config.get("config_path", ""),
            "command": public_config.get("command", ""),
            "autostart": public_config.get("autostart"),
            "autorestart": public_config.get("autorestart"),
            "startsecs": public_config.get("startsecs"),
            "startretries": public_config.get("startretries"),
            "config": public_config,
            "restart_count": status.get("restart_count", 0),
            "restart_events": status.get("restart_events", []),
            "last_failure_at": status.get("last_failure_at", ""),
            "last_error": status.get("last_error", ""),
            "evidence": {
                "title": f"supervisor program config {program} @ {host_id}",
                "locator": f"supervisor:{config.get('config_path', program)}@{host_id}",
                "excerpt": (
                    f"command={public_config.get('command', '')}; "
                    f"autostart={public_config.get('autostart')}; "
                    f"autorestart={public_config.get('autorestart')}; "
                    f"startsecs={public_config.get('startsecs')}; "
                    f"startretries={public_config.get('startretries')}"
                ),
            },
            **self._simulation_note(host_id),
        }

    def _elastic_documents(self, host_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        data = self._host(host_id)
        elastic = data.get("elasticsearch")
        if not isinstance(elastic, dict) or elastic.get("available") is False:
            raise BackendUnavailableError(
                f"Elasticsearch is unavailable on {host_id} in this mock environment"
            )
        documents = [doc for doc in elastic.get("documents", []) if isinstance(doc, dict)]
        return elastic, documents

    def _filter_elastic(
        self,
        documents: list[dict[str, Any]],
        *,
        index_pattern: str,
        service: str | None,
        level: str | None,
        query: str | None,
        since: str | None,
        until: str | None,
    ) -> list[dict[str, Any]]:
        since_dt = _parse_ts(since)
        until_dt = _parse_ts(until)
        needle = (query or "").lower()
        result: list[dict[str, Any]] = []
        for doc in documents:
            index = str(doc.get("index", ""))
            if not fnmatch.fnmatch(index, index_pattern):
                continue
            if service and str(doc.get("service", "")) != service:
                continue
            if level and not _level_matches(doc.get("level"), level):
                continue
            ts = _parse_ts(doc.get("@timestamp") or doc.get("ts"))
            if ts is None:
                continue
            if since_dt and ts < since_dt:
                continue
            if until_dt and ts > until_dt:
                continue
            if needle:
                haystack = " ".join(
                    str(doc.get(key, ""))
                    for key in ("message", "error_type", "trace_id", "service")
                ).lower()
                if needle not in haystack:
                    continue
            result.append(doc)
        return result

    async def elasticsearch_logs(
        self,
        host_id: str,
        *,
        index_pattern: str,
        service: str | None,
        level: str | None,
        query: str | None,
        since: str | None,
        until: str | None,
        limit: int,
        sort: str,
    ) -> dict[str, Any]:
        elastic, documents = self._elastic_documents(host_id)
        matches = self._filter_elastic(
            documents,
            index_pattern=index_pattern,
            service=service,
            level=level,
            query=query,
            since=since,
            until=until,
        )
        matches.sort(
            key=lambda doc: _parse_ts(doc.get("@timestamp") or doc.get("ts"))
            or datetime.min.replace(tzinfo=_LOCAL_TZ),
            reverse=sort != "asc",
        )
        entries = [
            {
                "index": doc.get("index", ""),
                "timestamp": doc.get("@timestamp") or doc.get("ts", ""),
                "service": doc.get("service", ""),
                "level": doc.get("level", ""),
                "message": doc.get("message", ""),
                "error_type": doc.get("error_type", ""),
                "trace_id": doc.get("trace_id", ""),
            }
            for doc in matches[: max(1, limit)]
        ]
        matched_indices = sorted({doc.get("index", "") for doc in matches})
        return {
            "host": host_id,
            "cluster": elastic.get("cluster", ""),
            "index_pattern": index_pattern,
            "matched_indices": matched_indices,
            "total": len(matches),
            "returned": len(entries),
            "entries": entries,
            "filters": {
                "service": service,
                "level": level,
                "query": query,
                "since": since,
                "until": until,
                "sort": sort,
            },
            "source": "elasticsearch",
            "evidence": {
                "title": f"Elasticsearch {index_pattern} hits={len(matches)} @ {host_id}",
                "locator": f"es:{index_pattern}@{host_id}",
                "excerpt": "\n".join(
                    f"{entry['timestamp']} {entry['level']} {entry['service']} {entry['message']}"
                    for entry in entries[:3]
                ),
            },
            **self._simulation_note(host_id),
        }

    async def aggregate_error_logs(
        self,
        host_id: str,
        *,
        index_pattern: str,
        service: str | None,
        level: str | None,
        query: str | None,
        since: str | None,
        until: str | None,
        group_by: str,
        interval: str,
        limit: int,
    ) -> dict[str, Any]:
        elastic, documents = self._elastic_documents(host_id)
        matches = self._filter_elastic(
            documents,
            index_pattern=index_pattern,
            service=service,
            level=level or "err",
            query=query,
            since=since,
            until=until,
        )
        buckets: dict[str, dict[str, Any]] = {}
        for doc in matches:
            message = str(doc.get("message", ""))
            error_type = str(doc.get("error_type") or "unknown")
            timestamp = str(doc.get("@timestamp") or doc.get("ts", ""))
            if group_by == "service":
                key = str(doc.get("service", ""))
            elif group_by == "level":
                key = str(doc.get("level", ""))
            elif group_by == "message_fingerprint":
                key = re.sub(r"\b\d+\b", "<n>", message.lower())[:120]
            elif group_by == "time_bucket":
                key = self._time_bucket(timestamp, interval)
            else:
                key = error_type
            bucket = buckets.setdefault(
                key,
                {
                    "key": key,
                    "count": 0,
                    "first_ts": timestamp,
                    "last_ts": timestamp,
                    "sample_message": message[:240],
                    "services": set(),
                    "error_types": set(),
                },
            )
            bucket["count"] += 1
            bucket["first_ts"] = min(bucket["first_ts"], timestamp)
            bucket["last_ts"] = max(bucket["last_ts"], timestamp)
            bucket["services"].add(str(doc.get("service", "")))
            bucket["error_types"].add(error_type)
        grouped = sorted(
            (
                {
                    **bucket,
                    "services": sorted(bucket["services"]),
                    "error_types": sorted(bucket["error_types"]),
                }
                for bucket in buckets.values()
            ),
            key=lambda bucket: (-bucket["count"], bucket["key"]),
        )[: max(1, limit)]
        return {
            "host": host_id,
            "cluster": elastic.get("cluster", ""),
            "index_pattern": index_pattern,
            "group_by": group_by,
            "interval": interval,
            "total_errors": len(matches),
            "buckets": grouped,
            "filters": {
                "service": service,
                "level": level or "err",
                "query": query,
                "since": since,
                "until": until,
            },
            "source": "elasticsearch",
            "evidence": {
                "title": f"Elasticsearch error aggregation ({len(matches)} errors) @ {host_id}",
                "locator": f"es-agg:{index_pattern}@{host_id}",
                "excerpt": "; ".join(
                    f"{bucket['key']}={bucket['count']}" for bucket in grouped[:4]
                ),
            },
            **self._simulation_note(host_id),
        }

    @staticmethod
    def _time_bucket(timestamp: str, interval: str) -> str:
        parsed = _parse_ts(timestamp)
        if parsed is None:
            return "unknown"
        seconds = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400}.get(interval, 60)
        epoch = int(parsed.timestamp())
        bucket = epoch - (epoch % seconds)
        return datetime.fromtimestamp(bucket, tz=_LOCAL_TZ).isoformat()

    async def logstash_pipeline_status(
        self, host_id: str, pipeline_id: str | None
    ) -> dict[str, Any]:
        data = self._host(host_id)
        logstash = data.get("logstash")
        if not isinstance(logstash, dict) or logstash.get("available") is False:
            raise BackendUnavailableError(
                f"Logstash is unavailable on {host_id} in this mock environment"
            )
        pipelines = [
            pipeline
            for pipeline in logstash.get("pipelines", [])
            if isinstance(pipeline, dict)
            and (pipeline_id is None or pipeline.get("pipeline_id") == pipeline_id)
        ]
        if pipeline_id and not pipelines:
            raise OpsNotFound(f"Logstash pipeline {pipeline_id} not found on {host_id}")
        states = [str(pipeline.get("state", "unknown")) for pipeline in pipelines]
        summary = {
            "total": len(pipelines),
            "running": states.count("running"),
            "failed": states.count("failed"),
            "unavailable": states.count("unavailable"),
        }
        return {
            "host": host_id,
            "pipeline_id": pipeline_id,
            "pipelines": pipelines,
            "summary": summary,
            "source": "logstash-api",
            "evidence": {
                "title": f"Logstash pipelines ({summary['total']}) @ {host_id}",
                "locator": f"logstash:pipelines@{host_id}",
                "excerpt": "; ".join(
                    f"{pipeline.get('pipeline_id')}={pipeline.get('state')}"
                    for pipeline in pipelines
                ),
            },
            **self._simulation_note(host_id),
        }

    async def service_catalog(self, host_id: str) -> list[dict[str, Any]]:
        """Read-only listing for the monitoring console, never a tool input."""
        data = self._host(host_id)
        return [
            {"name": name, "service": name, **record}
            for name, record in sorted((data.get("services") or {}).items())
        ]

    async def package_catalog(self, host_id: str) -> list[dict[str, Any]]:
        data = self._host(host_id)
        return [
            {
                "name": record.get("name"),
                "version": record.get("version"),
                "release": record.get("release"),
                "arch": record.get("arch"),
                "state": record.get("state", "installed"),
                "vendor": record.get("vendor", ""),
                "install_time": record.get("install_time", ""),
                "requires": record.get("requires", []),
            }
            for record in data.get("packages", [])
        ]

    async def restart_service(
        self, host_id: str, service: str, reason: str, operator: str
    ) -> dict[str, Any]:
        data = self._host(host_id)
        services = data.get("services", {})
        record = services.get(service)
        if record is None:
            raise OpsNotFound(f"service {service} not found on {host_id}")
        # Mock never pretends the service recovered: it reports the simulated
        # attempt only, so a demo cannot be mistaken for a real remediation.
        return {
            "host": host_id,
            "service": service,
            "restart_attempted": True,
            "simulated": "true",
            "operator": operator,
            "reason": reason,
            "next_state": record.get("state"),
            "note": "mock backend: no real process was restarted",
            "evidence": {
                "title": f"restart attempt {service} @ {host_id} (simulated)",
                "locator": f"action:restart:{service}@{host_id}",
                "excerpt": f"operator={operator}; reason={reason}; simulated=true",
            },
        }


class OpsNotFound(Exception):
    """Internal signal so tools can map it to a typed AppError."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def build_backend(
    name: str, hosts: list[HostProfile], fixtures: dict[str, dict[str, object]]
) -> OpsBackend:
    if name == "mock":
        return MockBackend(hosts, fixtures)  # type: ignore[arg-type]
    if name == "local":
        return LocalBackend(hosts)
    if name == "ssh":
        return SshBackend(hosts)
    raise BackendUnavailableError(f"unknown ops backend: {name}")
