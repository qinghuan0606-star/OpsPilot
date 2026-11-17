"""OpsPilot ops-plane schema (replaces the e-commerce tables).

Revision ID: 0001_ops
Revises:
Create Date: 2026-11-16

The e-commerce migrations (orders / returns) were removed together with the
domain: their tables are not referenced by any surviving model. Runtime still
calls ``Base.metadata.create_all`` for SQLite convenience, but the canonical
PostgreSQL path is this migration.

Verified with ``alembic upgrade head`` against SQLite in the development note;
see docs/第二阶段-业务迁移记录.md for the exact command and result.
"""

import sqlalchemy as sa

from alembic import op

revision = "0001_ops"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("host_id", sa.String(64), primary_key=True),
        sa.Column("hostname", sa.String(128), nullable=False, server_default=""),
        sa.Column("os_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("os_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("kernel", sa.String(64), nullable=False, server_default=""),
        sa.Column("arch", sa.String(32), nullable=False, server_default="x86_64"),
        sa.Column("backend", sa.String(16), nullable=False, server_default="mock"),
        sa.Column("labels", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "packages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("host_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False, index=True),
        sa.Column("epoch", sa.String(16), nullable=False, server_default="0"),
        sa.Column("version", sa.String(64), nullable=False, server_default=""),
        sa.Column("release", sa.String(64), nullable=False, server_default=""),
        sa.Column("arch", sa.String(32), nullable=False, server_default="x86_64"),
        sa.Column("state", sa.String(16), nullable=False, server_default="installed"),
        sa.Column("license", sa.String(128), nullable=False, server_default=""),
        sa.Column("vendor", sa.String(128), nullable=False, server_default=""),
        sa.Column("install_time", sa.String(64), nullable=False, server_default=""),
        sa.Column("requires", sa.Text, nullable=False),
        sa.Column("provides", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "services",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("host_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False, index=True),
        sa.Column("manager", sa.String(16), nullable=False, server_default="systemd"),
        sa.Column("state", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("since", sa.String(64), nullable=False, server_default=""),
        sa.Column("pid", sa.Integer, nullable=True),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("restart_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unit_path", sa.String(256), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "diagnosis_runs",
        sa.Column("trace_id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("intent", sa.String(32), nullable=False, server_default=""),
        sa.Column("strategy", sa.String(16), nullable=False, server_default=""),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("citations_json", sa.Text, nullable=False),
        sa.Column("tool_trace_json", sa.Text, nullable=False),
        sa.Column("retrieval_json", sa.Text, nullable=False),
        sa.Column("evidence_sufficient", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("evidence_gaps", sa.Text, nullable=False),
        sa.Column("refused", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("latency_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("document_id", sa.String(128), primary_key=True),
        sa.Column("title", sa.String(256), nullable=False, server_default=""),
        sa.Column("category", sa.String(32), nullable=False, server_default="linux_basics"),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="self_written"),
        sa.Column("source_note", sa.Text, nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "idempotency_keys",
        "audit_logs",
        "messages",
        "sessions",
        "knowledge_documents",
        "diagnosis_runs",
        "services",
        "packages",
        "hosts",
    ):
        op.drop_table(table)
