"""Extract service / package / host targets from a free-text ops question.

Deterministic string matching only: planning and argument filling must not
depend on the model guessing whether the user meant nginx or sshd.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

KNOWN_SERVICES: tuple[str, ...] = (
    "nginx",
    "sshd",
    "docker",
    "supervisor",
    "app-worker",
    "containerd",
    "firewalld",
    "network",
    "crond",
)
# ``supervisor`` is both a manager name and (historically) a unit name. The
# extractor treats it as a manager unless a concrete managed program is named.
_MANAGER_WORDS: tuple[str, ...] = ("supervisor", "supervisord")
KNOWN_PACKAGES: tuple[str, ...] = (
    "nginx-mod-http-geoip",
    "nginx",
    "docker-ce",
    "openssl-libs",
    "systemd",
    "glibc",
    "supervisor",
    "kernel",
    "containerd.io",
    "zlib",
)
_HOST = re.compile(r"\b(lab-node-\d+|host-\d+)\b", re.IGNORECASE)
_PKG_TOKEN = re.compile(r"\b([a-z][a-z0-9+._-]{2,30})\b")
_EXPLICIT_SERVICE = re.compile(r"([a-z][a-z0-9_-]{2,30})\.service\b", re.IGNORECASE)
_RPM_FILE = re.compile(r"\b([a-z][a-z0-9+._-]{1,40})\.rpm\b", re.IGNORECASE)
_RPM_COMMAND = re.compile(
    r"\brpm\s+(?:-q|--query|-i|-ivh|-U|-Uvh|-e|--erase)\s+([a-z][a-z0-9+._-]{1,40})",
    re.IGNORECASE,
)
_RPM_FILE_SUFFIX = re.compile(r"-[0-9][a-z0-9.+_~]*$", re.IGNORECASE)
_PACKAGE_CUES = (
    "rpm",
    "软件包",
    "包管理",
    "依赖",
    "安装",
    "升级",
    "卸载",
    "版本",
    "yum",
    "dnf",
    "package",
    "repo",
)

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "linux",
    "systemd",
    "systemctl",
    "journalctl",
    "rpm",
    "yum",
    "dnf",
    "log",
    "error",
    "failed",
    "root",
    "usr",
    "var",
    "etc",
    "lib",
    "service",
    "start",
    "status",
    "info",
    "sudo",
    "cpu",
    "memory",
    "disk",
    "open",
    "cannot",
    "file",
    "not",
    "found",
}


@dataclass(frozen=True)
class ServiceTarget:
    """What the user actually named, and which manager owns it.

    ``manager_only`` means the query only mentions Supervisor as a manager but
    no managed program; planning must ask for the program instead of guessing.
    """

    name: str | None
    manager: Literal["systemd", "supervisor"] | None = None
    manager_only: bool = False


def extract_host(query: str) -> str | None:
    match = _HOST.search(query)
    return match.group(1).lower() if match else None


def _has_manager_word(query: str) -> bool:
    lowered = query.lower()
    return any(
        re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", lowered) for word in _MANAGER_WORDS
    )


def _known_service_candidates(query: str) -> list[tuple[int, int, str]]:
    """Return (length, position, name), longest and earliest first."""
    lowered = query.lower()
    candidates: list[tuple[int, int, str]] = []
    for name in KNOWN_SERVICES:
        match = re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", lowered)
        if match:
            candidates.append((len(name), match.start(), name))
    return sorted(candidates, key=lambda item: (-item[0], item[1]))


def extract_service_target(query: str) -> ServiceTarget:
    """Resolve the service or Supervisor program named in the question.

    Order:
    1. explicit ``xxx.service``;
    2. the longest concrete program name (``app-worker`` beats ``supervisor``);
    3. Supervisor mentioned with no program -> manager_only, no guessed name;
    4. service names outside the whitelist -> None.
    """
    explicit = _EXPLICIT_SERVICE.search(query)
    if explicit:
        name = explicit.group(1).lower()
        manager: Literal["systemd", "supervisor"] | None = (
            "supervisor" if name in _MANAGER_WORDS else None
        )
        return ServiceTarget(name=name, manager=manager)

    candidates = _known_service_candidates(query)
    programs = [item for item in candidates if item[2] not in _MANAGER_WORDS]
    if programs:
        _length, _pos, name = programs[0]
        return ServiceTarget(
            name=name,
            manager="supervisor" if _has_manager_word(query) else None,
        )

    if _has_manager_word(query):
        return ServiceTarget(name=None, manager="supervisor", manager_only=True)

    if candidates:
        # Only a manager-like token remains; never turn it into a service guess.
        _length, _pos, name = candidates[0]
        return ServiceTarget(name=name, manager=None)
    return ServiceTarget(name=None)


def extract_service(query: str) -> str | None:
    return extract_service_target(query).name


def _package_name_from_token(token: str) -> str:
    """Trim an explicit ``name-version-release.arch`` token to its package name."""
    name = token.strip()
    if name.lower().endswith(".rpm"):
        name = name[:-4]
    while True:
        trimmed = _RPM_FILE_SUFFIX.sub("", name)
        if trimmed == name:
            return name
        name = trimmed


def extract_package(query: str) -> str | None:
    """Extract only a package the user actually named.

    No arbitrary English token is treated as a package: an unknown package
    must be clarified instead of guessed (package whitelist expansion belongs
    to the ops-tool phase).
    """
    lowered = query.lower()
    explicit_file = _RPM_FILE.search(lowered)
    if explicit_file:
        return _package_name_from_token(explicit_file.group(1))

    for name in KNOWN_PACKAGES:
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", lowered):
            if name in _MANAGER_WORDS and not any(cue in lowered for cue in _PACKAGE_CUES):
                # "Supervisor 反复重启" names a manager, not a package.
                continue
            return name

    command = _RPM_COMMAND.search(lowered)
    if command:
        token = _package_name_from_token(command.group(1))
        if token not in _STOPWORDS:
            return token
    return None
