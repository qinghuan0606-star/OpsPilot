"""Functional checks for the ops knowledge base (not an evaluation benchmark).

These assert *plumbing and retrievability*: every document parses, chunks keep
their provenance, expected documents are retrievable, re-ingest is idempotent
and a shrunk document does not leave stale vectors behind.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.config.settings import Settings
from app.core.enums import DocumentCategory
from app.providers.embeddings import HashEmbeddingProvider
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.ingest import ingest_to_memory
from app.retrieval.vector import (
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorRecord,
    chunk_from_payload,
    payload_for_chunk,
)
from app.schemas.retrieval import RetrievedChunk

KNOWLEDGE = "knowledge"


def _settings() -> Settings:
    return Settings(app_env="testing", embedding_dim=512)


def _build():
    return asyncio.run(
        ingest_to_memory(KNOWLEDGE, HashEmbeddingProvider(512), settings=_settings())
    )


@pytest.fixture(scope="module")
def corpus():
    bm25, store, chunks = _build()
    return SimpleNamespace(bm25=bm25, store=store, chunks=chunks)


def test_corpus_parses_into_non_empty_unique_chunks(corpus) -> None:
    chunks = corpus.chunks
    assert len({chunk.document_id for chunk in chunks}) >= 29
    assert len(chunks) >= 250
    assert all(chunk.content.strip() for chunk in chunks)
    ids = [chunk.chunk_id for chunk in chunks]
    assert len(ids) == len(set(ids))
    sections = {chunk.section for chunk in chunks}
    assert len(sections) > 1, "section headings must survive chunking"


def test_every_chunk_carries_provenance_for_citations(corpus) -> None:
    for chunk in corpus.chunks:
        meta = chunk.metadata
        assert chunk.title.strip()
        assert meta["doc_id"].strip()
        assert meta["source_type"] in {"self_written", "public_summary"}
        assert meta["source_note"].strip()
        assert meta["source_url"].startswith("http")
        assert meta["system"] in {
            "linux_generic",
            "openeuler",
            "kylin_v10",
            "openeuler_kylin_v10",
        }
        assert meta["applicable_version"].strip()
        assert meta["updated_at"].strip()
        assert chunk.category in set(DocumentCategory)


@pytest.mark.parametrize(
    ("query", "expected_prefix"),
    [
        ("rpm 依赖缺失 怎么查哪个包提供", "rpm_query_and_verify"),
        ("rpm 安装 文件冲突 怎么处理", "rpm_install_uninstall"),
        ("systemctl 服务启动失败 怎么排查", "systemd_service_lifecycle"),
        ("supervisor 进程自动重启 配置", "supervisor_autorestart_logs"),
        ("elasticsearch 日志索引 查询不到数据", "elasticsearch_log_store"),
        ("kibana 索引模式 看不到字段", "kibana_query_visualize"),
        ("linux 怎么把用户加入用户组", "linux_users_and_groups"),
        ("磁盘有空间但是 inode 满了", "linux_disk_filesystem"),
        ("openEuler 和 麒麟 V10 有什么区别", "os_differences_openeuler_kylin"),
    ],
)
def test_expected_document_is_retrievable(corpus, query: str, expected_prefix: str) -> None:
    hits = corpus.bm25.search(query, top_k=5)
    documents = [chunk.document_id for chunk in hits]
    assert any(document.startswith(expected_prefix) for document in documents), documents


def test_hybrid_search_keeps_provenance(corpus) -> None:
    class _FixedEmbedder:
        async def embed(self, texts):
            return [[1.0] + [0.0] * 511 for _ in texts]

    memory = InMemoryVectorStore()
    memory.replace_documents(
        [VectorRecord(chunk=chunk, embedding=[1.0] + [0.0] * 511) for chunk in corpus.chunks]
    )
    from app.retrieval.vector import VectorRetriever

    hybrid = HybridRetriever(
        BM25Retriever(corpus.chunks), VectorRetriever(memory, _FixedEmbedder()), rrf_k=60
    )
    hits = asyncio.run(hybrid.retrieve("supervisor 自动重启 配置", top_k=5))
    assert hits
    for chunk in hits:
        assert chunk.metadata["source_url"].startswith("http")
        assert chunk.metadata["doc_id"]


def test_repeat_ingest_is_idempotent() -> None:
    _, _, first = _build()
    _, _, second = _build()
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len(first) == len(second)


def test_replace_document_drops_stale_chunks() -> None:
    store = InMemoryVectorStore()
    long_doc = [
        RetrievedChunk(
            chunk_id=f"doc_{index:02d}",
            document_id="doc",
            title="t",
            content=f"part {index}",
            score=0.0,
            category=DocumentCategory.LINUX_BASICS,
        )
        for index in range(3)
    ]
    store.replace_documents([VectorRecord(chunk=chunk, embedding=[1.0]) for chunk in long_doc])
    short_doc = long_doc[:1]
    store.replace_documents([VectorRecord(chunk=chunk, embedding=[1.0]) for chunk in short_doc])
    hits = store.search([1.0], top_k=10)
    assert [chunk.chunk_id for chunk in hits] == ["doc_00"]


def test_payload_roundtrip_keeps_citation_fields() -> None:
    chunk = RetrievedChunk(
        chunk_id="doc_00",
        document_id="doc_abc",
        title="标题",
        content="内容",
        score=0.0,
        category=DocumentCategory.RPM_PACKAGE,
        section="依赖",
        policy_version="v1",
        metadata={
            "source": "knowledge/doc.md",
            "doc_id": "doc",
            "source_type": "self_written",
            "source_note": "note",
            "source_url": "https://example.com/doc",
            "system": "openeuler",
            "applicable_version": "24.03",
            "updated_at": "2026-11-17",
        },
    )
    restored = chunk_from_payload("point-id", payload_for_chunk(chunk), score=0.5, rank=1)
    assert restored.title == chunk.title
    assert restored.category is DocumentCategory.RPM_PACKAGE
    assert restored.metadata == chunk.metadata


def test_qdrant_replace_deletes_each_document_before_upsert() -> None:
    class _Client:
        def __init__(self) -> None:
            self.deleted: list[str] = []
            self.upserted = 0

        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="ops_knowledge")])

        def delete(self, *, collection_name, points_selector):
            self.deleted.append(points_selector.filter.must[0].match.value)

        def upsert(self, *, collection_name, points):
            self.upserted += len(points)

    store = QdrantVectorStore("http://localhost:6333", "ops_knowledge", dim=2)
    client = _Client()
    store._client = client
    records = [
        VectorRecord(
            chunk=RetrievedChunk(
                chunk_id="a_00",
                document_id="a",
                title="a",
                content="a",
                score=0.0,
                category=DocumentCategory.LINUX_BASICS,
            ),
            embedding=[1.0, 0.0],
        ),
        VectorRecord(
            chunk=RetrievedChunk(
                chunk_id="b_00",
                document_id="b",
                title="b",
                content="b",
                score=0.0,
                category=DocumentCategory.LINUX_BASICS,
            ),
            embedding=[0.0, 1.0],
        ),
    ]
    store.replace_documents(records)
    assert client.deleted == ["a", "b"]
    assert client.upserted == 2


def test_knowledge_documents_api_exposes_provenance() -> None:
    from fastapi.testclient import TestClient

    from app.config.settings import clear_settings_cache
    from app.main import create_app

    clear_settings_cache()
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/ops/knowledge/documents")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(body["documents"]) >= 29
    for document in body["documents"]:
        assert document["title"].strip()
        assert document["source_url"].startswith("http")
        assert document["system"]
        assert document["updated_at"]
        assert document["doc_format"] in {"runbook", "quick_reference"}
