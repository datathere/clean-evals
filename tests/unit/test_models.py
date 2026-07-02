"""Tests for the public Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from clean_evals.models import (
    Case,
    CaseResult,
    Dataset,
    ModelResponse,
    RunConfig,
    ScoreResult,
)


def test_case_id_validation() -> None:
    Case(id="ok_id-1.2:3", input={})
    with pytest.raises(ValidationError):
        Case(id="bad id with spaces", input={})
    with pytest.raises(ValidationError):
        Case(id="", input={})


def test_dataset_rejects_duplicate_case_ids() -> None:
    with pytest.raises(ValidationError):
        Dataset(
            name="d",
            version="v1",
            scorer="exact_match",
            cases=[Case(id="x", input={}), Case(id="x", input={})],
        )


def test_dataset_version_pattern() -> None:
    Dataset(name="d", version="v1", scorer="s", cases=[])
    Dataset(name="d", version="0.1.0", scorer="s", cases=[])
    Dataset(name="d", version="1.2.3-beta", scorer="s", cases=[])
    with pytest.raises(ValidationError):
        Dataset(name="d", version="latest", scorer="s", cases=[])


def test_run_config_rejects_floating_alias() -> None:
    with pytest.raises(ValidationError):
        RunConfig(models=["claude-3-5-sonnet-latest"])
    with pytest.raises(ValidationError):
        RunConfig(models=["latest"])
    RunConfig(models=["gpt-4o-2024-11-20"])


def test_run_config_exempts_local_models_from_alias_rule() -> None:
    """local/ models are pinned by the file on disk, so any tag is valid."""
    RunConfig(models=["local/llama3.2:latest"])
    RunConfig(models=["local/some-model-latest"])


def test_run_config_temperature_bounds() -> None:
    RunConfig(models=["m-2024-01-01"], temperature=0.0)
    RunConfig(models=["m-2024-01-01"], temperature=2.0)
    with pytest.raises(ValidationError):
        RunConfig(models=["m-2024-01-01"], temperature=-0.1)
    with pytest.raises(ValidationError):
        RunConfig(models=["m-2024-01-01"], temperature=2.1)


def test_run_config_max_cost_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        RunConfig(models=["m-2024-01-01"], max_cost_usd=0)


def test_score_result_clamps_score_range() -> None:
    ScoreResult(score=0.0, passed=False)
    ScoreResult(score=1.0, passed=True)
    with pytest.raises(ValidationError):
        ScoreResult(score=1.1, passed=True)
    with pytest.raises(ValidationError):
        ScoreResult(score=-0.1, passed=False)


def test_models_are_frozen() -> None:
    r = ModelResponse(content="x", latency_ms=1, cost_usd=0.0)
    with pytest.raises((ValidationError, TypeError)):
        r.content = "y"  # type: ignore[misc]
    cr = CaseResult(
        case_id="c",
        model="m-2024-01-01",
        status="ok",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    with pytest.raises((ValidationError, TypeError)):
        cr.status = "error"  # type: ignore[misc]


def test_dataset_from_yaml_roundtrip(tmp_path: Path) -> None:
    yml = tmp_path / "ds.yml"
    yml.write_text(
        yaml.safe_dump(
            {
                "name": "d",
                "version": "v1",
                "scorer": "exact_match",
                "cases": [{"id": "c1", "input": {"text": "hi"}, "expected": {"label": "x"}}],
            }
        ),
        encoding="utf-8",
    )
    ds = Dataset.from_yaml(yml)
    assert ds.cases[0].id == "c1"

    out = tmp_path / "out.yml"
    ds.to_yaml(out)
    again = Dataset.from_yaml(out)
    assert again == ds


def test_dataset_from_yaml_rejects_unknown_keys(tmp_path: Path) -> None:
    yml = tmp_path / "bad.yml"
    yml.write_text(
        yaml.safe_dump(
            {
                "name": "d",
                "version": "v1",
                "scorer": "exact_match",
                "cases": [],
                "unknown": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        Dataset.from_yaml(yml)


def test_dataset_from_yaml_with_jsonl(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        '{"id": "c1", "input": {"x": 1}, "expected": {"y": 2}}\n', encoding="utf-8"
    )
    yml = tmp_path / "ds.yml"
    yml.write_text(
        yaml.safe_dump(
            {
                "name": "d",
                "version": "v1",
                "scorer": "s",
                "cases_jsonl": "cases.jsonl",
            }
        ),
        encoding="utf-8",
    )
    ds = Dataset.from_yaml(yml)
    assert ds.cases == [Case(id="c1", input={"x": 1}, expected={"y": 2})]


def test_dataset_from_yaml_runs_scrubber(tmp_path: Path) -> None:
    yml = tmp_path / "ds.yml"
    yml.write_text(
        yaml.safe_dump(
            {
                "name": "d",
                "version": "v1",
                "scorer": "s",
                "cases": [
                    {"id": "c1", "input": {"email": "a@b.com"}, "expected": None},
                ],
            }
        ),
        encoding="utf-8",
    )

    class Scrub:
        def scrub(self, case: Case) -> Case:
            return case.model_copy(update={"input": {"email": "REDACTED"}})

    ds = Dataset.from_yaml(yml, scrubber=Scrub())
    assert ds.cases[0].input == {"email": "REDACTED"}
