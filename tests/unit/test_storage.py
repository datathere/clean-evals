"""Storage layer tests against a SQLite engine."""

from __future__ import annotations

from datetime import UTC, datetime

from clean_evals.models import Case, Dataset, RunConfig, RunResult
from clean_evals.storage.artifacts import LocalArtifactStore, build_artifact_store
from clean_evals.storage.db import session_factory
from clean_evals.storage.repo import (
    cumulative_cost_today,
    hydrate_run,
    persist_run,
    upsert_dataset,
)


def _ds() -> Dataset:
    return Dataset(
        name="d",
        version="v1",
        scorer="exact_match",
        cases=[
            Case(id="c1", input={"prompt": "p1"}, expected={"text": "want1"}),
            Case(id="c2", input={"prompt": "p2"}, expected={"text": "want2"}),
        ],
    )


def test_upsert_dataset_creates_then_replaces_cases(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        row = upsert_dataset(session, _ds())
        session.commit()
    assert row.id is not None

    new_ds = _ds().model_copy(
        update={
            "cases": [Case(id="x", input={"prompt": "p"}, expected={"text": "y"})],
        }
    )
    with factory() as session:
        row = upsert_dataset(session, new_ds)
        session.commit()
        assert len(row.cases) == 1
        assert row.cases[0].case_id_external == "x"


def test_persist_and_hydrate_roundtrip(sqlite_engine) -> None:
    factory = session_factory()
    ds = _ds()
    with factory() as session:
        upsert_dataset(session, ds)
        session.commit()

    now = datetime.now(UTC)
    result = RunResult(
        run_id="r_unit_001",
        dataset=ds.name,
        dataset_version=ds.version,
        config=RunConfig(models=["m-2024-01-01"]),
        cases=[],
        summary={},
        started_at=now,
        finished_at=now,
        pricing_version="2026.04",
        deterministic=True,
    )
    with factory() as session:
        persist_run(session, result=result, artifact_uri=None, triggered_by="test")
        session.commit()

    with factory() as session:
        again = hydrate_run(session, "r_unit_001")
    assert again is not None
    assert again.run_id == "r_unit_001"


def test_cumulative_cost_today(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        spent = cumulative_cost_today(session, datetime.now(UTC).replace(hour=0))
    assert spent == 0.0


def test_local_artifact_store_roundtrip(tmp_path) -> None:
    store = LocalArtifactStore(root=tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "report.md").write_text("# hi", encoding="utf-8")
    uri = store.write_dir("r_1", src)
    assert "r_1" in uri
    listing = store.list(uri)
    assert "report.md" in listing
    with store.open_read(uri, "report.md") as fh:
        assert fh.read() == b"# hi"


def test_build_artifact_store_is_local(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLEAN_EVALS_ARTIFACT_DIR", str(tmp_path))
    assert isinstance(build_artifact_store(), LocalArtifactStore)
