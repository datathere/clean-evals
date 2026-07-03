"""Persisted background-job state (``jobs`` table).

Candidate generation and inline eval runs execute in server-side
background tasks. Their progress lives in the database so that status
survives server restarts and is visible across worker processes.

Every writer opens a short session from the factory and commits
immediately — callers run in background threads and event loops, so no
session is ever shared.

``updated_at`` is the heartbeat. A ``running`` row whose heartbeat is
older than ``STALE_AFTER_S`` belongs to a process that died; readers
treat it as lost rather than letting it block new work forever.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from clean_evals.storage.db import JobRow

STALE_AFTER_S = 900
"""Heartbeats land at least once per model call; 15 minutes is generous."""

GENERATION = "generation"
INLINE_RUN = "inline_run"


def create(factory: sessionmaker[Session], *, kind: str, dataset_id: int, total: int = 0) -> int:
    """Insert a ``running`` job row and return its id."""
    with factory() as session:
        row = JobRow(kind=kind, dataset_id=dataset_id, total=total)
        session.add(row)
        session.commit()
        return row.id


def update(factory: sessionmaker[Session], job_id: int, **fields: object) -> None:
    """Apply ``fields`` to the job row and refresh the heartbeat."""
    with factory() as session:
        row = session.get(JobRow, job_id)
        if row is None:
            return
        for name, value in fields.items():
            setattr(row, name, value)
        row.updated_at = datetime.now(UTC)
        session.commit()


def latest(session: Session, *, kind: str, dataset_id: int) -> JobRow | None:
    """The most recent job of ``kind`` for a dataset, or ``None``."""
    return session.execute(
        select(JobRow)
        .where(JobRow.kind == kind, JobRow.dataset_id == dataset_id)
        .order_by(JobRow.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def is_active(row: JobRow | None) -> bool:
    """Whether the row represents live, still-heartbeating work."""
    if row is None or row.status != "running":
        return False
    heartbeat = row.updated_at
    if heartbeat.tzinfo is None:
        # SQLite returns naive datetimes; values are stored in UTC.
        heartbeat = heartbeat.replace(tzinfo=UTC)
    return datetime.now(UTC) - heartbeat < timedelta(seconds=STALE_AFTER_S)


def mark_lost_if_stale(factory: sessionmaker[Session], row: JobRow | None) -> JobRow | None:
    """Convert a stale ``running`` row into an ``error`` row, in place."""
    if row is None or row.status != "running" or is_active(row):
        return row
    update(factory, row.id, status="error", detail="lost: the serving process restarted")
    row.status = "error"
    row.detail = "lost: the serving process restarted"
    return row
