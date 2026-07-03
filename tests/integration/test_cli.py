"""CLI commands driven end to end against the fake provider.

The CLI is the primary interface, so these exercise the real Typer app,
the runner, storage, and reporters with no API cost. A local dataset that
uses ``local/fake-1`` scores deterministically.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clean_evals.cli import app

pytestmark = pytest.mark.integration

runner = CliRunner()

DATASET_YML = """\
name: cli_sentiment
version: v1
scorer: exact_match
scorer_config:
  field: label
cases:
  - id: c1
    input: {prompt: "I love this, it is great"}
    expected: {label: positive}
  - id: c2
    input: {prompt: "I hate this, it is terrible"}
    expected: {label: negative}
"""


@pytest.fixture
def dataset_file(tmp_path: Path) -> Path:
    path = tmp_path / "dataset.yml"
    path.write_text(DATASET_YML, encoding="utf-8")
    return path


def test_list_commands(migrated_sqlite: str) -> None:
    for cmd, expected in (
        ("list-adapters", "local"),
        ("list-scorers", "exact_match"),
        ("list-reporters", "markdown"),
        ("list-models", "anthropic"),
    ):
        result = runner.invoke(app, [cmd])
        assert result.exit_code == 0, result.output
        assert expected in result.output


def test_run_persists_and_show_diff(
    migrated_sqlite: str, fake_openai_server: str, dataset_file: Path, tmp_path: Path
) -> None:
    out = tmp_path / "results"
    result = runner.invoke(
        app,
        [
            "run",
            str(dataset_file),
            "--models",
            "local/fake-1",
            "--max-cost",
            "1.0",
            "--output",
            str(out),
            "--reporters",
            "markdown,jsonl",
            "--persist",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out / "run.md").exists() or any(out.glob("run*.md"))

    # A persisted run is show-able and diff-able against itself.
    from clean_evals.storage.db import RunRow, session_factory

    with session_factory()() as session:
        run_ids = [r.id for r in session.query(RunRow).all()]
    assert run_ids
    run_id = run_ids[0]

    shown = runner.invoke(app, ["show", run_id])
    assert shown.exit_code == 0, shown.output
    assert "local/fake-1" in shown.output

    diffed = runner.invoke(app, ["diff", run_id, run_id])
    assert diffed.exit_code == 0, diffed.output


def test_run_below_score_threshold_exits_2(
    migrated_sqlite: str, fake_openai_server: str, tmp_path: Path
) -> None:
    # Expected answers the fake model will never produce -> score 0.
    ds = tmp_path / "impossible.yml"
    ds.write_text(
        "name: imp\nversion: v1\nscorer: exact_match\nscorer_config: {field: label}\n"
        "cases:\n  - id: c1\n    input: {prompt: hello}\n    expected: {label: WRONG}\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "run",
            str(ds),
            "--models",
            "local/fake-1",
            "--max-cost",
            "1.0",
            "--output",
            str(tmp_path / "o"),
            "--reporters",
            "jsonl",
            "--fail-on-score",
            "0.5",
        ],
    )
    assert result.exit_code == 2, result.output


def test_run_invalid_dataset_exits_3(migrated_sqlite: str, tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text("name: x\nversion: v1\n", encoding="utf-8")  # missing scorer/cases
    result = runner.invoke(
        app, ["run", str(bad), "--models", "local/fake-1", "--output", str(tmp_path / "o")]
    )
    assert result.exit_code == 3, result.output


def test_show_unknown_run_exits_3(migrated_sqlite: str) -> None:
    result = runner.invoke(app, ["show", "r_nope"])
    assert result.exit_code == 3


def test_diff_unknown_run_exits_3(migrated_sqlite: str) -> None:
    result = runner.invoke(app, ["diff", "r_a", "r_b"])
    assert result.exit_code == 3


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "clean-evals" in result.output


def test_build_seeds_a_dataset(migrated_sqlite: str, tmp_path: Path, monkeypatch) -> None:
    """`build` seeds an in-progress dataset; stub serve so it returns."""
    import clean_evals.cli as cli_mod

    served: dict[str, object] = {}
    monkeypatch.setattr(cli_mod, "serve", lambda **kw: served.update(kw))

    inputs = tmp_path / "inputs.csv"
    inputs.write_text("id,ticket\nt1,my card was charged twice\n", encoding="utf-8")
    result = runner.invoke(
        app, ["build", str(inputs), "--name", "tickets", "--scorer", "exact_match"]
    )
    assert result.exit_code == 0, result.output
    assert "Seeded dataset" in result.output

    from clean_evals.storage.db import CaseRow, DatasetRow, session_factory

    with session_factory()() as session:
        ds = session.query(DatasetRow).filter_by(name="tickets").one()
        assert session.query(CaseRow).filter_by(dataset_id=ds.id).count() == 1


def test_generate_cli_produces_candidates(
    migrated_sqlite: str, fake_openai_server: str, tmp_path: Path
) -> None:
    from clean_evals.storage.db import CandidateOutputRow, CaseRow, DatasetRow, session_factory

    with session_factory()() as session:
        ds = DatasetRow(name="gen", version="v1", scorer="exact_match", scorer_config={})
        session.add(ds)
        session.flush()
        session.add(CaseRow(dataset_id=ds.id, case_id_external="c1", input_jsonb={"prompt": "hi"}))
        session.commit()
        dataset_id = ds.id

    result = runner.invoke(app, ["generate", str(dataset_id), "--models", "local/fake-1"])
    assert result.exit_code == 0, result.output

    with session_factory()() as session:
        count = (
            session.query(CandidateOutputRow)
            .join(CaseRow, CaseRow.id == CandidateOutputRow.case_id)
            .filter(CaseRow.dataset_id == dataset_id)
            .count()
        )
    assert count == 1


def test_migrate_command_is_idempotent(migrated_sqlite: str) -> None:
    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0, result.output
    assert "Migrated" in result.output


def test_calibrate_without_ratings_exits_3(migrated_sqlite: str, fake_openai_server: str) -> None:
    from clean_evals.storage.db import DatasetRow, session_factory

    with session_factory()() as session:
        ds = DatasetRow(name="cal", version="v1", scorer="llm_judge", scorer_config={})
        session.add(ds)
        session.commit()
        dataset_id = ds.id

    result = runner.invoke(app, ["calibrate", str(dataset_id), "--judge", "local/fake-1"])
    assert result.exit_code == 3, result.output


def test_run_fail_on_regression_exits_1(
    migrated_sqlite: str, fake_openai_server: str, dataset_file: Path, tmp_path: Path
) -> None:
    # First run: perfect score, persisted as the baseline.
    base = runner.invoke(
        app,
        [
            "run",
            str(dataset_file),
            "--models",
            "local/fake-1",
            "--max-cost",
            "1.0",
            "--output",
            str(tmp_path / "a"),
            "--reporters",
            "jsonl",
            "--persist",
        ],
    )
    assert base.exit_code == 0, base.output

    from clean_evals.storage.db import RunRow, session_factory

    with session_factory()() as session:
        baseline_id = session.query(RunRow).one().id

    # Second run against a dataset whose expected answers changed so the
    # fake model now scores worse -> regression vs the baseline.
    worse = tmp_path / "worse.yml"
    worse.write_text(
        "name: cli_sentiment\nversion: v1\nscorer: exact_match\n"
        "scorer_config: {field: label}\ncases:\n"
        "  - id: c1\n    input: {prompt: neutral thing}\n    expected: {label: positive}\n"
        "  - id: c2\n    input: {prompt: neutral thing}\n    expected: {label: negative}\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "run",
            str(worse),
            "--models",
            "local/fake-1",
            "--max-cost",
            "1.0",
            "--output",
            str(tmp_path / "b"),
            "--reporters",
            "jsonl",
            "--baseline",
            baseline_id,
            "--fail-on-regression",
        ],
    )
    assert result.exit_code == 1, result.output
