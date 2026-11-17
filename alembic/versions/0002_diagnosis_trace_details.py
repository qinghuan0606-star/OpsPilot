"""Persist planner and critic details for diagnosis/trace pages.

Revision ID: 0002_diag_trace
Revises: 0001_ops
Create Date: 2026-11-17

Additive only: existing diagnosis_runs rows remain valid. SQLite startup also
uses SQLAlchemy ``create_all``, which creates this missing table in place.
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_diag_trace"
down_revision = "0001_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_traces",
        sa.Column("trace_id", sa.String(64), primary_key=True),
        sa.Column("plan_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("critic_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("critic_round", sa.Integer, nullable=False, server_default="0"),
        sa.Column("execution_status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("diagnosis_traces")
