"""Knowledge corpus: ops-only files, seven domains, provable provenance."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.enums import DocumentCategory
from app.retrieval.chunking import document_id_from_path
from app.retrieval.ingest import category_for_stem
from app.retrieval.unstructured_parser import list_knowledge_files

KNOWLEDGE = Path("knowledge")
_SUFFIXES = {".md", ".pdf", ".docx", ".pptx", ".html", ".htm", ".txt"}


def test_corpus_covers_the_seven_ops_domains() -> None:
    files = list_knowledge_files(KNOWLEDGE)
    assert len(files) >= 15
    assert {path.suffix.lower() for path in files} <= _SUFFIXES
    categories = {category_for_stem(path.stem) for path in files}
    assert categories == set(DocumentCategory)
    # No e-commerce residue.
    stems = " ".join(path.stem for path in files)
    for banned in ("order", "refund", "coupon", "return_policy", "shipping"):
        assert banned not in stems


def test_category_prefix_is_exact_not_substring() -> None:
    assert category_for_stem("linux_commands_basics") == DocumentCategory.LINUX_BASICS
    assert category_for_stem("os_openeuler_baseline") == DocumentCategory.DOMESTIC_OS
    assert category_for_stem("rpm_dependency_conflict") == DocumentCategory.RPM_PACKAGE
    assert category_for_stem("systemd_service_lifecycle") == DocumentCategory.SERVICE_MGMT
    assert category_for_stem("journalctl_usage") == DocumentCategory.LOG_FAULT
    assert category_for_stem("disk_usage_diagnosis") == DocumentCategory.NETWORK_DISK
    assert category_for_stem("sudo_and_umask") == DocumentCategory.SECURITY_PERM
    assert category_for_stem("elasticsearch_log_store") == DocumentCategory.LOG_FAULT
    assert category_for_stem("logstash_pipeline") == DocumentCategory.LOG_FAULT
    assert category_for_stem("kibana_query_visualize") == DocumentCategory.LOG_FAULT
    assert category_for_stem("unknown_topic") == DocumentCategory.LINUX_BASICS


def test_every_document_declares_source_and_applicable_version() -> None:
    manifest = json.loads((KNOWLEDGE / "_manifest.json").read_text(encoding="utf-8"))
    documents = manifest["documents"]
    documented = {f"{stem}.md" for stem in documents}
    files = {path.name for path in KNOWLEDGE.glob("*.md")}
    assert documented == files
    allowed_sources = {"self_written", "public_summary", "upstream_manual_excerpt"}
    for entry in documents.values():
        assert entry["title"].strip()
        assert entry["source_type"] in allowed_sources
        assert entry["source_note"].strip()
        assert entry["applicable_version"].strip()
        assert entry["system"] in {
            "linux_generic",
            "openeuler",
            "kylin_v10",
            "openeuler_kylin_v10",
        }
        assert entry["source_url"].startswith("http")
        assert entry["updated_at"].strip()
        assert entry["doc_format"] in {"runbook", "quick_reference"}
        # The hard constraint: nothing may claim vendor-internal documentation.
        assert "麒麟信安" not in entry["source_note"]


def test_document_id_is_independent_of_checkout_location(tmp_path: Path) -> None:
    first = tmp_path / "checkout-a" / "knowledge"
    second = tmp_path / "checkout-b" / "knowledge"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    assert document_id_from_path(
        first / "rpm_query_and_verify.md", root=first
    ) == document_id_from_path(second / "rpm_query_and_verify.md", root=second)
