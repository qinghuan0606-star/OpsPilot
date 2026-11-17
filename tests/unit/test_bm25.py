from app.core.enums import DocumentCategory
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.chunking import chunk_markdown, stable_chunk_id


def test_chunk_ids_are_stable() -> None:
    text = "## A\n\nhello world\n\n## B\n\nsecond section about returns"
    once = chunk_markdown(
        text,
        document_id="rpm_dependency_conflict",
        title="t",
        category=DocumentCategory.LOG_FAULT,
        source="x",
    )
    twice = chunk_markdown(
        text,
        document_id="rpm_dependency_conflict",
        title="t",
        category=DocumentCategory.LOG_FAULT,
        source="x",
    )
    assert [c.chunk_id for c in once] == [c.chunk_id for c in twice]
    assert once[0].chunk_id == stable_chunk_id("rpm_dependency_conflict", 0)


def test_bm25_ranks_lexical_match() -> None:
    chunks = chunk_markdown(
        "## 依赖冲突\n\n升级后提示 missing libGeoIP.so.1。需同步升级模块子包。\n\n## 校验\n\nrpm -V 校验文件完整性。",
        document_id="doc",
        title="policy",
        category=DocumentCategory.LOG_FAULT,
        source="x",
    )
    retriever = BM25Retriever(chunks)
    hits = retriever.search("依赖 缺失 模块", top_k=2)
    assert hits
    assert "依赖" in hits[0].content or "libGeoIP" in hits[0].content
