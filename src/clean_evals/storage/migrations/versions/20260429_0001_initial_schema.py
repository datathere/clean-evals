"""initial schema

Revision ID: 20260429_0001
Revises:
Create Date: 2026-04-29

Creates: datasets, cases, runs, case_results, schedules.
Schema is portable across MySQL 8 and Postgres 16. JSON columns use the
generic SQLAlchemy ``JSON`` type which both back ends support natively.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260429_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scorer", sa.String(100), nullable=False),
        sa.Column("scorer_config", sa.JSON, nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("name", "version", name="uq_datasets_name_version"),
    )
    op.create_index("ix_datasets_name", "datasets", ["name"])

    op.create_table(
        "cases",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id_external", sa.String(200), nullable=False),
        sa.Column("input_jsonb", sa.JSON, nullable=False),
        sa.Column("expected_jsonb", sa.JSON, nullable=True),
        sa.Column("tags_jsonb", sa.JSON, nullable=False),
        sa.Column("locked", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("metadata_jsonb", sa.JSON, nullable=False),
        sa.Column("rev", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_cases_dataset_id", "cases", ["dataset_id"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_version", sa.String(40), nullable=False),
        sa.Column("config_jsonb", sa.JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_jsonb", sa.JSON, nullable=False),
        sa.Column("artifact_uri", sa.String(500), nullable=True),
        sa.Column("pricing_version", sa.String(20), nullable=False),
        sa.Column("triggered_by", sa.String(40), nullable=False, server_default="cli"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_runs_dataset_id", "runs", ["dataset_id"])
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "case_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", sa.String(80), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("case_id", sa.String(200), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("passed", sa.Boolean, nullable=True),
        sa.Column("response_jsonb", sa.JSON, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=True),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_case_results_run_id", "case_results", ["run_id"])
    op.create_index("ix_case_results_case_id", "case_results", ["case_id"])
    op.create_index("ix_case_results_model", "case_results", ["model"])

    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "dataset_id",
            sa.Integer,
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cron", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("config_jsonb", sa.JSON, nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_schedules_dataset_id", "schedules", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_schedules_dataset_id", table_name="schedules")
    op.drop_table("schedules")
    op.drop_index("ix_case_results_model", table_name="case_results")
    op.drop_index("ix_case_results_case_id", table_name="case_results")
    op.drop_index("ix_case_results_run_id", table_name="case_results")
    op.drop_table("case_results")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_dataset_id", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_cases_dataset_id", table_name="cases")
    op.drop_table("cases")
    op.drop_index("ix_datasets_name", table_name="datasets")
    op.drop_table("datasets")
