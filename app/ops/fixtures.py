"""Load mock host fixtures from app/ops/data.

Fixtures are simulated lab snapshots, not recordings of any real machine.
Every tool response derived from them carries `simulated=true` so a demo can
never be mistaken for production telemetry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.ops.hosts import HostProfile


def default_fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def load_fixtures(
    directory: str | Path | None = None,
) -> tuple[list[HostProfile], dict[str, dict[str, Any]]]:
    base = Path(directory) if directory else default_fixtures_dir()
    hosts: list[HostProfile] = []
    fixtures: dict[str, dict[str, Any]] = {}
    if not base.exists():
        return hosts, fixtures
    for path in sorted(base.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        host_id = str(data.get("host_id") or path.stem)
        data.setdefault("host_id", host_id)
        os_info = data.get("os", {})
        hosts.append(
            HostProfile(
                host_id=host_id,
                hostname=str(data.get("hostname", host_id)),
                os_name=str(os_info.get("name", "")),
                os_version=str(os_info.get("version", "")),
                kernel=str(os_info.get("kernel", "")),
                arch=str(os_info.get("arch", "x86_64")),
                backend="mock",
                labels=list(data.get("labels", [])),
                note=str(data.get("note", "")),
            )
        )
        fixtures[host_id] = data
    return hosts, fixtures
