"""golden path: prompt spec, candidate outputs, ratings, judge configs

Revision ID: 20260701_0002
Revises: 20260429_0001
Create Date: 2026-07-01

Adds the storage for stages 1-4 of the golden path (docs/docs/flow.md):

- ``datasets`` gains the prompt spec (request_shape, system_prompt,
  shared_context, user_template).
- ``candidate_outputs`` — stage 2, one model output per (case, model).
- ``ratings`` — stage 3, human review of one candidate output.
- ``judge_configs`` — stage 4, versioned calibrated judge standards.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_0002"
down_revision: str | None = "20260429_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("request_shape", sa.String(20), nullable=False, server_default="raw"),
    )
    op.add_column("datasets", sa.Column("system_prompt", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("shared_context", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("user_template", sa.Text(), nullable=True))

    op.create_table(
        "candidate_outputs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "case_id",
            sa.Integer,
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("parsed_jsonb", sa.JSON, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=True),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("case_id", "model", name="uq_candidates_case_model"),
    )
    op.create_index("ix_candidate_outputs_case_id", "candidate_outputs", ["case_id"])
    op.create_index("ix_candidate_outputs_model", "candidate_outputs", ["model"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "candidate_output_id",
            sa.Integer,
            sa.ForeignKey("candidate_outputs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ratings_candidate_output_id", "ratings", ["candidate_output_id"])

    op.create_table(
        "judge_configs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("judge_model", sa.String(120), nullable=False),
        sa.Column("rubric", sa.Text(), nullable=False),
        sa.Column("few_shot_jsonb", sa.JSON, nullable=False),
        sa.Column("agreement_jsonb", sa.JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_judge_configs_dataset_id", "judge_configs", ["dataset_id"])


def downgrade() -> None:
    op.drop_table("judge_configs")
    op.drop_table("ratings")
    op.drop_table("candidate_outputs")
    op.drop_column("datasets", "user_template")
    op.drop_column("datasets", "shared_context")
    op.drop_column("datasets", "system_prompt")
    op.drop_column("datasets", "request_shape")
