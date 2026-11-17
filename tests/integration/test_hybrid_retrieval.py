"""Hybrid BM25 + vector retrieval over the ops knowledge base."""

import pytest

from app.config.settings import clear_settings_cache, get_settings
from app.providers.embeddings import HashEmbeddingProvider
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.ingest import ingest_to_memory
from app.retrieval.vector import VectorRetriever


@pytest.mark.asyncio
async def test_hybrid_retrieves_nginx_upgrade_case() -> None:
    clear_settings_cache()
    settings = get_settings()
    embedder = HashEmbeddingProvider(dim=settings.embedding_dim)
    bm25, store, chunks = await ingest_to_memory("knowledge", embedder, settings=settings)
    assert chunks
    retriever = HybridRetriever(bm25, VectorRetriever(store, embedder), rrf_k=settings.rrf_k)
    hits = await retriever.retrieve("nginx 升级后启动失败 dlopen libGeoIP", top_k=5)
    assert hits
    blob = " ".join(hit.content for hit in hits)
    assert "dlopen" in blob or "libGeoIP" in blob or "模块" in blob
    assert hits[0].metadata.get("source_type") in {"self_written", "public_summary"}
