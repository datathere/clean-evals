"""Starter dataset seeding — pristine installs only, idempotent."""

from __future__ import annotations

from sqlalchemy import select

from clean_evals.starter import STARTER_NAME, seed_starter_dataset
from clean_evals.storage.db import CaseRow, DatasetRow, session_factory


def test_seeds_once_on_pristine_db(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        ds_id = seed_starter_dataset(session)
        assert ds_id is not None

    with factory() as session:
        ds = session.get(DatasetRow, ds_id)
        assert ds is not None
        assert ds.name == STARTER_NAME
        assert ds.request_shape == "templated"
        assert ds.system_prompt is not None
        assert "billing" in ds.system_prompt
        cases = session.execute(select(CaseRow).where(CaseRow.dataset_id == ds_id)).scalars().all()
        assert len(cases) == 12
        assert all(c.expected_jsonb is None and not c.locked for c in cases)

        # Two golden samples are runnable at once.
        names = {d.name: d for d in session.execute(select(DatasetRow)).scalars()}
        assert set(names) == {STARTER_NAME, "sample-sentiment", "sample-summaries"}
        for golden in ("sample-sentiment", "sample-summaries"):
            rows = (
                session.execute(select(CaseRow).where(CaseRow.dataset_id == names[golden].id))
                .scalars()
                .all()
            )
            assert rows
            assert all(c.expected_jsonb is not None and c.locked for c in rows)
        assert names["sample-summaries"].scorer == "llm_judge"

    # Second call is a no-op.
    with factory() as session:
        assert seed_starter_dataset(session) is None


def test_never_seeds_when_a_dataset_exists(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        session.add(DatasetRow(name="mine", version="v1", scorer="exact_match", scorer_config={}))
        session.commit()
    with factory() as session:
        assert seed_starter_dataset(session) is None
