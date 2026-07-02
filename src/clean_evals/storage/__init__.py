"""Storage layer.

clean-evals owns its own data. SQLite is the zero-config default; the
schema is portable to MySQL and Postgres via SQLAlchemy 2.x for teams.
Alembic migrations live under ``clean_evals.storage.migrations`` and ship
inside the wheel so ``clean-evals migrate`` works out of the box.

Two complementary stores:

- The relational DB holds runs, datasets, schedules.
- The :class:`ArtifactStore` (local filesystem) holds large blobs:
  rendered Markdown reports, JSONL streams, per-case diffs.

The split avoids stuffing megabytes of Markdown into database ``TEXT``
columns. ``ArtifactStore`` is a protocol, so alternative backends can be
provided by wrapping ``build_artifact_store``.
"""

from __future__ import annotations

from clean_evals.storage.artifacts import (
    ArtifactStore,
    LocalArtifactStore,
    build_artifact_store,
)
from clean_evals.storage.db import (
    Base,
    CaseResultRow,
    CaseRow,
    DatasetRow,
    RunRow,
    ScheduleRow,
    create_engine_from_env,
    session_factory,
)

__all__ = [
    "ArtifactStore",
    "Base",
    "CaseResultRow",
    "CaseRow",
    "DatasetRow",
    "LocalArtifactStore",
    "RunRow",
    "ScheduleRow",
    "build_artifact_store",
    "create_engine_from_env",
    "session_factory",
]
