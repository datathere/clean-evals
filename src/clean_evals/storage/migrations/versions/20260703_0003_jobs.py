"""jobs: persisted background-work state

Revision ID: 20260703_0003
Revises: 20260701_0002
Create Date: 2026-07-03

Candidate generation and inline eval runs previously tracked progress in
module-level dictionaries, which multiple worker processes cannot share
and a restart wipes. The ``jobs`` table replaces that state.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260703_0003"
down_revision: str | None = "20260701_0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_dataset_id", "jobs", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_dataset_id", table_name="jobs")
    op.drop_index("ix_jobs_kind", table_name="jobs")
    op.drop_table("jobs")
