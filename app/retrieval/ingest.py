"""Knowledge-base ingestion into BM25 and the vector store."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.core.enums import DocumentCategory
from app.providers.base import EmbeddingProvider
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.chunking import document_id_from_path
from app.retrieval.cleaning import dedupe_chunks
from app.retrieval.unstructured_parser import list_knowledge_files, parse_path
from app.retrieval.vector import (
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorRecord,
    build_records,
)
from app.schemas.retrieval import RetrievedChunk

# Prefix rules map file stems to the seven ops knowledge domains.
_CATEGORY_PREFIXES: tuple[tuple[str, DocumentCategory], ...] = (
    ("linux_", DocumentCategory.LINUX_BASICS),
    ("command_", DocumentCategory.LINUX_BASICS),
    ("process_", DocumentCategory.LINUX_BASICS),
    ("os_", DocumentCategory.DOMESTIC_OS),
    ("domestic_", DocumentCategory.DOMESTIC_OS),
    ("openeuler", DocumentCategory.DOMESTIC_OS),
    ("kylin", DocumentCategory.DOMESTIC_OS),
    ("rpm_", DocumentCategory.RPM_PACKAGE),
    ("package_", DocumentCategory.RPM_PACKAGE),
    ("systemd_", DocumentCategory.SERVICE_MGMT),
    ("supervisor_", DocumentCategory.SERVICE_MGMT),
    ("service_", DocumentCategory.SERVICE_MGMT),
    ("journal", DocumentCategory.LOG_FAULT),
    ("log_", DocumentCategory.LOG_FAULT),
    ("elasticsearch", DocumentCategory.LOG_FAULT),
    ("logstash", DocumentCategory.LOG_FAULT),
    ("kibana", DocumentCategory.LOG_FAULT),
    ("nginx_", DocumentCategory.LOG_FAULT),
    ("fault_", DocumentCategory.LOG_FAULT),
    ("disk_", DocumentCategory.NETWORK_DISK),
    ("network_", DocumentCategory.NETWORK_DISK),
    ("sudo_", DocumentCategory.SECURITY_PERM),
    ("selinux_", DocumentCategory.SECURITY_PERM),
    ("security_", DocumentCategory.SECURITY_PERM),
)

MANIFEST_NAME = "_manifest.json"


def category_for_stem(stem: str) -> DocumentCategory:
    lowered = stem.lower()
    for prefix, category in _CATEGORY_PREFIXES:
        if lowered == prefix.rstrip("_") or lowered.startswith(prefix):
            return category
    return DocumentCategory.LINUX_BASICS


def load_manifest(knowledge_dir: str | Path) -> dict[str, dict]:
    """Read provenance metadata so every chunk can state where it came from."""
    path = Path(knowledge_dir) / MANIFEST_NAME
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    documents = data.get("documents") or {}
    return documents if isinstance(documents, dict) else {}


class KnowledgeIngestor:
    def __init__(
        self,
        knowledge_dir: str,
        embedder: EmbeddingProvider,
        settings: Settings | None = None,
    ) -> None:
        self._knowledge_dir = Path(knowledge_dir)
        self._embedder = embedder
        self._settings = settings or get_settings()

    async def load(self) -> tuple[list[RetrievedChunk], list[VectorRecord]]:
        files = list_knowledge_files(self._knowledge_dir)
        manifest = load_manifest(self._knowledge_dir)
        chunks: list[RetrievedChunk] = []
        for path in files:
            meta = manifest.get(path.stem) or {}
            category = category_for_stem(path.stem)
            if meta.get("category"):
                try:
                    category = DocumentCategory(meta["category"])
                except ValueError:
                    pass
            document_id = document_id_from_path(path, root=self._knowledge_dir)
            title = str(meta.get("title") or path.stem)
            file_chunks = await asyncio.to_thread(
                parse_path,
                path,
                document_id=document_id,
                title=title,
                category=category,
                settings=self._settings,
            )
            provenance = {
                "doc_id": path.stem,
                "source_type": str(meta.get("source_type") or "self_written"),
                "source_note": str(meta.get("source_note") or ""),
                "source_url": str(meta.get("source_url") or ""),
                "system": str(meta.get("system") or "linux_generic"),
                "applicable_version": str(meta.get("applicable_version") or ""),
                "updated_at": str(meta.get("updated_at") or ""),
            }
            file_chunks = [
                chunk.model_copy(update={"metadata": {**chunk.metadata, **provenance}})
                for chunk in file_chunks
            ]
            chunks.extend(file_chunks)
        chunks = dedupe_chunks(chunks)
        if not chunks:
            return [], []
        embeddings = await self._embedder.embed([chunk.content for chunk in chunks])
        records = build_records(chunks, embeddings)
        return chunks, records


async def ingest_to_memory(
    knowledge_dir: str,
    embedder: EmbeddingProvider,
    settings: Settings | None = None,
) -> tuple[BM25Retriever, InMemoryVectorStore, list[RetrievedChunk]]:
    ingestor = KnowledgeIngestor(knowledge_dir, embedder, settings=settings)
    chunks, records = await ingestor.load()
    bm25 = BM25Retriever(chunks)
    store = InMemoryVectorStore()
    store.replace_documents(records)
    return bm25, store, chunks


async def ingest_knowledge(
    knowledge_dir: str,
    embedder: EmbeddingProvider,
    *,
    settings: Settings | None = None,
    qdrant_url: str = "",
    qdrant_collection: str = "ops_knowledge",
    embedding_dim: int = 512,
) -> tuple[BM25Retriever, InMemoryVectorStore | QdrantVectorStore, list[RetrievedChunk]]:
    """Prefer Qdrant when configured; fall back to memory if Qdrant is down."""
    logger = logging.getLogger(__name__)
    resolved = settings or get_settings()
    ingestor = KnowledgeIngestor(knowledge_dir, embedder, settings=resolved)
    chunks, records = await ingestor.load()
    bm25 = BM25Retriever(chunks)
    if qdrant_url:
        store = QdrantVectorStore(qdrant_url, qdrant_collection, embedding_dim)
        try:
            await asyncio.to_thread(store.replace_documents, records)
            return bm25, store, chunks
        except Exception:
            logger.warning("qdrant_ingest_failed_using_memory")
    memory = InMemoryVectorStore()
    memory.replace_documents(records)
    return bm25, memory, chunks
