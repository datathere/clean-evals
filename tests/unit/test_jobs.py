"""Persisted background-job state (jobs table)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clean_evals import jobs
from clean_evals.storage.db import DatasetRow, JobRow, session_factory


def _dataset(factory) -> int:
    with factory() as session:
        row = DatasetRow(name="d", version="v1", scorer="exact_match", scorer_config={})
        session.add(row)
        session.commit()
        return row.id


def test_job_lifecycle(sqlite_engine) -> None:
    factory = session_factory()
    dataset_id = _dataset(factory)

    job_id = jobs.create(factory, kind=jobs.GENERATION, dataset_id=dataset_id, total=4)
    jobs.update(factory, job_id, done=2, cost_usd=0.5)
    jobs.update(factory, job_id, status="done", done=4)

    with factory() as session:
        row = jobs.latest(session, kind=jobs.GENERATION, dataset_id=dataset_id)
    assert row is not None
    assert row.id == job_id
    assert row.status == "done"
    assert row.done == 4
    assert row.cost_usd == 0.5
    assert not jobs.is_active(row)


def test_latest_returns_newest_of_kind(sqlite_engine) -> None:
    factory = session_factory()
    dataset_id = _dataset(factory)

    first = jobs.create(factory, kind=jobs.INLINE_RUN, dataset_id=dataset_id)
    jobs.update(factory, first, status="done", run_id="r_1")
    second = jobs.create(factory, kind=jobs.INLINE_RUN, dataset_id=dataset_id)
    jobs.create(factory, kind=jobs.GENERATION, dataset_id=dataset_id)

    with factory() as session:
        row = jobs.latest(session, kind=jobs.INLINE_RUN, dataset_id=dataset_id)
    assert row is not None
    assert row.id == second
    assert jobs.is_active(row)


def test_stale_running_job_is_marked_lost(sqlite_engine) -> None:
    """A running row whose heartbeat stopped belongs to a dead process."""
    factory = session_factory()
    dataset_id = _dataset(factory)
    job_id = jobs.create(factory, kind=jobs.INLINE_RUN, dataset_id=dataset_id)

    stale = datetime.now(UTC) - timedelta(seconds=jobs.STALE_AFTER_S + 60)
    with factory() as session:
        row = session.get(JobRow, job_id)
        assert row is not None
        row.updated_at = stale
        session.commit()

    with factory() as session:
        row = jobs.latest(session, kind=jobs.INLINE_RUN, dataset_id=dataset_id)
    assert not jobs.is_active(row)
    marked = jobs.mark_lost_if_stale(factory, row)
    assert marked is not None
    assert marked.status == "error"
    with factory() as session:
        persisted = jobs.latest(session, kind=jobs.INLINE_RUN, dataset_id=dataset_id)
    assert persisted is not None
    assert persisted.status == "error"
    assert persisted.detail is not None


def test_fresh_running_job_is_not_marked_lost(sqlite_engine) -> None:
    factory = session_factory()
    dataset_id = _dataset(factory)
    job_id = jobs.create(factory, kind=jobs.INLINE_RUN, dataset_id=dataset_id)

    with factory() as session:
        row = jobs.latest(session, kind=jobs.INLINE_RUN, dataset_id=dataset_id)
    marked = jobs.mark_lost_if_stale(factory, row)
    assert marked is not None
    assert marked.id == job_id
    assert marked.status == "running"
