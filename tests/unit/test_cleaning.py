import logging
from pathlib import Path

from app.core.constants import PII_MASK
from app.core.enums import DocumentCategory
from app.retrieval.chunking import chunk_markdown
from app.retrieval.cleaning import (
    NEAR_DUP_HAMMING,
    dedupe_chunks,
    hamming64,
    normalize_text,
    simhash64,
)
from app.retrieval.unstructured_parser import elements_to_chunks, parse_path
from app.schemas.retrieval import RetrievedChunk
from tests.unit.test_unstructured_parser import _FakeElement, _settings


def _chunk(chunk_id: str, document_id: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        title=document_id,
        content=content,
        score=0.0,
        category=DocumentCategory.LINUX_BASICS,
    )


def test_strips_bom_and_zero_width() -> None:
    raw = "\ufeff服\u200b务\u00ad状态"
    assert normalize_text(raw) == "服务状态"


def test_nfkc_fullwidth_digits_not_chinese_numerals() -> None:
    assert normalize_text("７天日志") == "7天日志"
    assert "7天" not in normalize_text("七天日志")
    assert normalize_text("七天日志") == "七天日志"


def test_joins_cjk_hard_breaks_but_not_tables() -> None:
    assert normalize_text("无理\n由", join_hard_breaks=True) == "无理由"
    assert "\n" in normalize_text("无理\n由", join_hard_breaks=False)
    chunks = elements_to_chunks(
        [_FakeElement("Table", "无理\n由", table_html="<table>无理\n由</table>")],
        document_id="disk_usage",
        title="disk_usage",
        category=DocumentCategory.NETWORK_DISK,
        source="t.pdf",
    )
    assert "\n" in chunks[0].content


def test_collapses_inline_space_and_extra_blank_lines() -> None:
    text = "保留 59\t天日志。\n\n\n\n过期删除。"
    cleaned = normalize_text(text)
    assert "\t" not in cleaned
    assert "保留 59 天日志。" in cleaned
    assert "\n\n\n" not in cleaned


def test_markdown_keeps_policy_pii_words_and_numbers(tmp_path: Path) -> None:
    path = tmp_path / "privacy_ops.md"
    path.write_text(
        "运维人员不得索取完整身份证。联系以 13812345678 为例不得复述。\n", encoding="utf-8"
    )
    chunks = parse_path(
        path,
        document_id="privacy",
        title="privacy_ops",
        category=DocumentCategory.SECURITY_PERM,
        settings=_settings(),
    )
    blob = " ".join(chunk.content for chunk in chunks)
    assert "身份证" in blob
    assert "13812345678" in blob


def test_non_markdown_masks_phone(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-fake")

    def fake_partition(_path: Path) -> list[_FakeElement]:
        return [_FakeElement("NarrativeText", "用户手机 13812345678 已登记。")]

    chunks = parse_path(
        path,
        document_id="scan",
        title="scan",
        category=DocumentCategory.LINUX_BASICS,
        settings=_settings(),
        partition_fn=fake_partition,
    )
    assert chunks
    assert "13812345678" not in chunks[0].content
    assert f"138{PII_MASK}5678" in chunks[0].content


def test_utf8_sig_markdown_reads_bom(tmp_path: Path) -> None:
    path = tmp_path / "journal.md"
    path.write_bytes("\ufeff# journalctl\n\n按服务过滤日志。\n".encode())
    chunks = parse_path(
        path,
        document_id="journal",
        title="journal",
        category=DocumentCategory.LINUX_BASICS,
        settings=_settings(),
    )
    assert chunks
    assert chunks[0].content.startswith("按服务过滤日志")


def test_exact_duplicate_keeps_first_chunk_id() -> None:
    first = _chunk("a_00", "doc_a", "rpm -V 用于校验文件完整性。")
    second = _chunk("b_00", "doc_b", "rpm -V 用于校验文件完整性。")
    kept = dedupe_chunks([first, second])
    assert [chunk.chunk_id for chunk in kept] == ["a_00"]


def test_near_duplicate_is_logged_not_dropped(caplog) -> None:
    text_a = "服务启动失败时先执行 systemctl status 查看退出码，再读 journalctl 日志。"
    text_b = "服务启动失败时先执行 systemctl status 查看退出码，再读 journalctl 日志！"
    distance = hamming64(simhash64(text_a), simhash64(text_b))
    assert 0 < distance <= NEAR_DUP_HAMMING or distance <= 8
    threshold = min(NEAR_DUP_HAMMING, distance) if distance <= NEAR_DUP_HAMMING else distance
    with caplog.at_level(logging.INFO, logger="app.retrieval.cleaning"):
        kept = dedupe_chunks(
            [_chunk("a_00", "service_failure", text_a), _chunk("b_00", "service_debug", text_b)],
            near_dup_bits=threshold,
        )
    assert len(kept) == 2
    assert any(record.message == "ingest_near_duplicate" for record in caplog.records)


def test_chunk_markdown_normalizes_fullwidth() -> None:
    chunks = chunk_markdown(
        "## 日志保留\n\n默认保留 ７天 日志。",
        document_id="doc",
        title="policy",
        category=DocumentCategory.LOG_FAULT,
        source="x.md",
    )
    assert "7天" in chunks[0].content
    assert chunks[0].metadata["parser"] == "markdown"
