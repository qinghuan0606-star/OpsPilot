"""Read-only ops console endpoints: hosts, services, packages, knowledge."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_container
from app.retrieval.ingest import load_manifest
from app.services.container import AppContainer

router = APIRouter(prefix="/ops", tags=["ops"])


def _knowledge_payload(
    stem: str,
    meta: dict,
    chunk_counts: dict[str, int],
) -> dict:
    return {
        "document_id": stem,
        "title": meta.get("title", stem),
        "category": meta.get("category", ""),
        "source_type": meta.get("source_type", ""),
        "source_note": meta.get("source_note", ""),
        "source_url": meta.get("source_url", ""),
        "system": meta.get("system", ""),
        "applicable_version": meta.get("applicable_version", ""),
        "doc_format": meta.get("doc_format", ""),
        "updated_at": meta.get("updated_at", ""),
        "chunk_count": chunk_counts.get(stem, 0),
    }


@router.get("/hosts")
async def list_hosts(container: AppContainer = Depends(get_container)) -> dict:
    """Allowed inspection targets. Fixtures are simulated lab hosts."""
    hosts = container.hosts.list_allowed()
    return {
        "hosts": [host.model_dump(mode="json") for host in hosts],
        "count": len(hosts),
        "backend": container.settings.ops_tool_backend,
    }


@router.get("/hosts/{host_id}/overview")
async def host_overview(
    host_id: str,
    container: AppContainer = Depends(get_container),
) -> dict:
    """One-shot snapshot for the monitoring page."""
    container.hosts.resolve(host_id, default=container.settings.ops_default_host)
    backend = container.ops_backend
    system = await backend.system_info(host_id)
    cpu_mem = await backend.cpu_memory(host_id, 5)
    disk = await backend.disk_usage(host_id, None)
    services = await backend.service_catalog(host_id)
    packages = await backend.package_catalog(host_id)
    failed = [item for item in services if item.get("state") == "failed"]
    log_target = failed[0].get("name") if failed else services[0].get("name") if services else None
    error_logs: dict = {"service": log_target, "source": "unavailable", "entries": []}
    if log_target:
        try:
            log_payload = await backend.service_logs(
                host_id, str(log_target), 30, None, None, None, "warn", None
            )
            error_logs = {
                "service": log_target,
                "source": log_payload.get("source", "journal"),
                "entries": log_payload.get("entries", []),
                "truncated": log_payload.get("truncated", False),
                "simulated": True,
            }
        except Exception:
            error_logs = {
                "service": log_target,
                "source": "unavailable",
                "entries": [],
                "simulated": True,
            }
    return {
        "host_id": host_id,
        "system": system,
        "resources": {"cpu": cpu_mem["cpu"], "memory": cpu_mem["memory"]},
        "top_processes": cpu_mem.get("top_processes", []),
        "disks": disk.get("filesystems", []),
        "inode_use_pct": disk.get("inode_use_pct"),
        "services": services,
        "packages": packages,
        "error_logs": error_logs,
        "simulated": True,
        "note": "模拟数据：用于演示与测试，不对应任何真实主机",
    }


@router.get("/services")
async def list_services(
    host_id: str = Query(default="", max_length=64),
    container: AppContainer = Depends(get_container),
) -> dict:
    host = container.hosts.resolve(host_id or None, default=container.settings.ops_default_host)
    services = await container.ops_backend.service_catalog(host.host_id)
    return {"host_id": host.host_id, "services": services, "count": len(services)}


@router.get("/packages")
async def list_packages(
    host_id: str = Query(default="", max_length=64),
    container: AppContainer = Depends(get_container),
) -> dict:
    host = container.hosts.resolve(host_id or None, default=container.settings.ops_default_host)
    packages = await container.ops_backend.package_catalog(host.host_id)
    return {"host_id": host.host_id, "packages": packages, "count": len(packages)}


@router.get("/tools")
async def list_tools(container: AppContainer = Depends(get_container)) -> dict:
    """Read-only tool catalog for the console.

    This exposes names, schemas, risk and read_only flags only; it does not
    execute anything. The same data remains available under the admin route.
    """
    tools = container.chat_service.registry.describe()
    return {
        "tools": tools,
        "names": [t["name"] for t in tools],
        "count": len(tools),
        "write_tools_enabled": container.settings.ops_enable_write_tools,
    }


@router.get("/knowledge/documents")
async def knowledge_documents(
    container: AppContainer = Depends(get_container),
) -> dict:
    """Manifest-backed provenance list, so the UI never invents a source."""
    manifest = load_manifest(container.settings.knowledge_dir)
    chunk_counts = container.retriever.document_chunk_counts()
    documents = [
        _knowledge_payload(stem, meta, chunk_counts) for stem, meta in sorted(manifest.items())
    ]
    return {"documents": documents, "count": len(documents)}


@router.get("/knowledge/documents/{document_id}")
async def knowledge_document(
    document_id: str,
    container: AppContainer = Depends(get_container),
) -> dict:
    """Manifest metadata plus the deterministic chunks currently indexed."""
    manifest = load_manifest(container.settings.knowledge_dir)
    meta = manifest.get(document_id)
    if meta is None:
        return {"found": False, "document_id": document_id}
    chunks = container.retriever.document_chunks(document_id)
    return {
        "found": True,
        "document": _knowledge_payload(
            document_id, meta, container.retriever.document_chunk_counts()
        ),
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "section": chunk.section,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
            }
            for chunk in chunks
        ],
    }
