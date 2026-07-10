"""telemetry: ingested interactions, derived exchanges, rating source

Revision ID: 20260710_0004
Revises: 20260703_0003
Create Date: 2026-07-10

Production telemetry lands in ``telemetry_interactions`` (the raw envelope,
kept lossless) and derives into ``telemetry_exchanges`` (one reviewable
(request, response) data point each). ``ratings.source`` distinguishes
blind-review ratings ("human") from telemetry-derived ones ("implicit") so
judge calibration can weight or exclude them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0004"
down_revision: str | None = "20260703_0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "telemetry_interactions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("interaction_id", sa.String(80), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("dataset_name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("envelope_jsonb", sa.JSON, nullable=False),
        sa.Column("classifier_cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "interaction_id", name="uq_telemetry_source_interaction"),
    )
    op.create_index("ix_telemetry_interactions_source", "telemetry_interactions", ["source"])
    op.create_index(
        "ix_telemetry_interactions_dataset_name", "telemetry_interactions", ["dataset_name"]
    )
    op.create_index("ix_telemetry_interactions_status", "telemetry_interactions", ["status"])

    op.create_table(
        "telemetry_exchanges",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "interaction_pk",
            sa.Integer,
            sa.ForeignKey("telemetry_interactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("context_jsonb", sa.JSON, nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("request_input_jsonb", sa.JSON, nullable=True),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("response_parsed_jsonb", sa.JSON, nullable=True),
        sa.Column("response_model", sa.String(120), nullable=False),
        sa.Column("alternatives_jsonb", sa.JSON, nullable=False),
        sa.Column("regen_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("label", sa.String(40), nullable=True),
        sa.Column("verdict", sa.String(20), nullable=True),
        sa.Column("rating", sa.Integer, nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("proposed_expected_jsonb", sa.JSON, nullable=True),
        sa.Column("judge_score", sa.Float, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="derived"),
        sa.Column(
            "promoted_case_id",
            sa.Integer,
            sa.ForeignKey("cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("auto_locked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("spot_check", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("spot_check_resolved", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_telemetry_exchanges_interaction_pk", "telemetry_exchanges", ["interaction_pk"]
    )
    op.create_index("ix_telemetry_exchanges_input_hash", "telemetry_exchanges", ["input_hash"])
    op.create_index(
        "ix_telemetry_exchanges_response_model", "telemetry_exchanges", ["response_model"]
    )
    op.create_index("ix_telemetry_exchanges_status", "telemetry_exchanges", ["status"])

    op.add_column(
        "ratings",
        sa.Column("source", sa.String(20), nullable=False, server_default="human"),
    )


def downgrade() -> None:
    op.drop_column("ratings", "source")
    op.drop_index("ix_telemetry_exchanges_status", table_name="telemetry_exchanges")
    op.drop_index("ix_telemetry_exchanges_response_model", table_name="telemetry_exchanges")
    op.drop_index("ix_telemetry_exchanges_input_hash", table_name="telemetry_exchanges")
    op.drop_index("ix_telemetry_exchanges_interaction_pk", table_name="telemetry_exchanges")
    op.drop_table("telemetry_exchanges")
    op.drop_index("ix_telemetry_interactions_status", table_name="telemetry_interactions")
    op.drop_index("ix_telemetry_interactions_dataset_name", table_name="telemetry_interactions")
    op.drop_index("ix_telemetry_interactions_source", table_name="telemetry_interactions")
    op.drop_table("telemetry_interactions")
