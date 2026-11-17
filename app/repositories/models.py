"""SQLAlchemy ORM models for OpsPilot."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.time import utcnow


class Base(DeclarativeBase):
    pass


class HostRow(Base):
    """Registered inspection target. Backend decides how it is read."""

    __tablename__ = "hosts"

    host_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(128), default="")
    os_name: Mapped[str] = mapped_column(String(64), default="")
    os_version: Mapped[str] = mapped_column(String(64), default="")
    kernel: Mapped[str] = mapped_column(String(64), default="")
    arch: Mapped[str] = mapped_column(String(32), default="x86_64")
    backend: Mapped[str] = mapped_column(String(16), default="mock")
    labels: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PackageRow(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    epoch: Mapped[str] = mapped_column(String(16), default="0")
    version: Mapped[str] = mapped_column(String(64), default="")
    release: Mapped[str] = mapped_column(String(64), default="")
    arch: Mapped[str] = mapped_column(String(32), default="x86_64")
    state: Mapped[str] = mapped_column(String(16), default="installed")
    license: Mapped[str] = mapped_column(String(128), default="")
    vendor: Mapped[str] = mapped_column(String(128), default="")
    install_time: Mapped[str] = mapped_column(String(64), default="")
    requires: Mapped[str] = mapped_column(Text, default="[]")
    provides: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServiceRow(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    manager: Mapped[str] = mapped_column(String(16), default="systemd")
    state: Mapped[str] = mapped_column(String(16), default="unknown")
    since: Mapped[str] = mapped_column(String(64), default="")
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    unit_path: Mapped[str] = mapped_column(String(256), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiagnosisRow(Base):
    """One answered turn, kept for the diagnosis history and trace pages."""

    __tablename__ = "diagnosis_runs"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    query: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str] = mapped_column(String(32), default="")
    strategy: Mapped[str] = mapped_column(String(16), default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    tool_trace_json: Mapped[str] = mapped_column(Text, default="[]")
    retrieval_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_sufficient: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence_gaps: Mapped[str] = mapped_column(Text, default="")
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiagnosisTraceRow(Base):
    """Plan/critic detail for one diagnosis run.

    Kept in a separate table so an existing ``diagnosis_runs`` SQLite/Postgres
    database only needs one additive ``CREATE TABLE`` migration; old rows stay
    readable and simply return no plan/critic detail.
    """

    __tablename__ = "diagnosis_traces"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    critic_json: Mapped[str] = mapped_column(Text, default="{}")
    critic_round: Mapped[int] = mapped_column(Integer, default=0)
    execution_status: Mapped[str] = mapped_column(String(32), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDocumentRow(Base):
    """Ingested knowledge document metadata, including provenance honesty flags."""

    __tablename__ = "knowledge_documents"

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    category: Mapped[str] = mapped_column(String(32), default="linux_basics")
    source_type: Mapped[str] = mapped_column(String(32), default="self_written")
    source_note: Mapped[str] = mapped_column(Text, default="")
    policy_version: Mapped[str] = mapped_column(String(32), default="v1")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLogRow(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
