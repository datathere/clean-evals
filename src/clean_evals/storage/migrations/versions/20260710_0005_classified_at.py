"""telemetry: classified_at timestamp for day-accurate budget accounting

Revision ID: 20260710_0005
Revises: 20260710_0004
Create Date: 2026-07-10

The classifier's daily ceiling was keyed on ``created_at`` (ingest time),
which misses spend recorded today on interactions ingested before UTC
midnight — a stalled backlog could re-spend the full ceiling every day.
``classified_at`` records when the classifier actually ran; the budget sums
over it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0005"
down_revision: str | None = "20260710_0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "telemetry_interactions",
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telemetry_interactions", "classified_at")
