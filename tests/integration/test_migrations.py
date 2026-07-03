"""Alembic migrations produce the schema the ORM expects."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect

from clean_evals.storage.db import Base

pytestmark = pytest.mark.integration


def test_upgrade_from_empty_creates_all_tables(migrated_sqlite: str) -> None:
    engine = create_engine(migrated_sqlite)
    try:
        have = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    expected = set(Base.metadata.tables) | {"alembic_version"}
    missing = expected - have
    assert not missing, f"migrations missing tables: {missing}"


def test_migrated_schema_has_jobs_columns(migrated_sqlite: str) -> None:
    engine = create_engine(migrated_sqlite)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("jobs")}
    finally:
        engine.dispose()
    assert {"kind", "status", "done", "run_id", "updated_at"} <= cols


def test_upgrade_is_idempotent(migrated_sqlite: str) -> None:
    """Running upgrade again on an already-migrated DB is a no-op."""
    from clean_evals.storage.migrations.runner import upgrade

    upgrade("head")  # must not raise
