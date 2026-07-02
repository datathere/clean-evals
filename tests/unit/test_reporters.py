"""Reporter output tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from clean_evals.models import (
    Case,
    CaseResult,
    ModelResponse,
    ModelSummary,
    RunConfig,
    RunResult,
    ScoreResult,
)
from clean_evals.reporters.diff import write_case_diff
from clean_evals.reporters.jsonl import JSONLReporter
from clean_evals.reporters.junit import JUnitReporter
from clean_evals.reporters.markdown import MarkdownReporter


def _result() -> RunResult:
    now = datetime.now(UTC)
    cases = [
        CaseResult(
            case_id="c1",
            model="m-2024-01-01",
            status="ok",
            response=ModelResponse(content="x", latency_ms=10, cost_usd=0.01),
            score=ScoreResult(score=1.0, passed=True),
            started_at=now,
            finished_at=now,
        ),
        CaseResult(
            case_id="c2",
            model="m-2024-01-01",
            status="ok",
            response=ModelResponse(content="y", latency_ms=12, cost_usd=0.02),
            score=ScoreResult(score=0.0, passed=False),
            started_at=now,
            finished_at=now,
        ),
    ]
    summary = {
        "m-2024-01-01": ModelSummary(
            model="m-2024-01-01",
            cases_run=2,
            cases_passed=1,
            score_mean=0.5,
            score_p50=0.5,
            latency_p95_ms=12,
            error_rate=0.0,
            total_cost_usd=0.03,
            cost_per_correct_usd=0.03,
            pricing_version="2026.04",
        )
    }
    return RunResult(
        run_id="r_test",
        dataset="d",
        dataset_version="v1",
        config=RunConfig(models=["m-2024-01-01"]),
        cases=cases,
        summary=summary,
        started_at=now,
        finished_at=now,
        pricing_version="2026.04",
        deterministic=True,
    )


def test_markdown_report_renders(tmp_path: Path) -> None:
    p = MarkdownReporter().write(_result(), tmp_path)
    body = p.read_text(encoding="utf-8")
    assert "# clean-evals run" in body
    assert "by datathere" in body  # footer attribution
    assert "Recommendations" in body


def test_jsonl_report_one_row_per_case(tmp_path: Path) -> None:
    p = JSONLReporter().write(_result(), tmp_path)
    lines = [
        json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) == 2
    assert {row["case_id"] for row in lines} == {"c1", "c2"}
    for line in lines:
        assert "score" in line
        assert "pricing_version" in line


def test_junit_report_is_valid_xml(tmp_path: Path) -> None:
    p = JUnitReporter().write(_result(), tmp_path)
    tree = ET.fromstring(p.read_text(encoding="utf-8"))
    assert tree.tag == "testsuites"
    suites = list(tree.iter("testsuite"))
    assert len(suites) == 1
    cases = list(tree.iter("testcase"))
    assert len(cases) == 2


def test_case_diff_writes_markdown(tmp_path: Path) -> None:
    case = Case(id="c1", input={"prompt": "hello"}, expected={"x": 1})
    cr = CaseResult(
        case_id="c1",
        model="m-2024-01-01",
        status="ok",
        response=ModelResponse(content='{"x": 2}', parsed={"x": 2}, latency_ms=1, cost_usd=0.0),
        score=ScoreResult(score=0.0, passed=False, breakdown={"x": 0.0}, notes="value mismatch"),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    p = write_case_diff(case, cr, tmp_path)
    body = p.read_text(encoding="utf-8")
    assert "Diff" in body
    assert "## Expected" in body
    assert "## Actual" in body
    assert "value mismatch" in body


def test_case_diff_sanitizes_model_ids_in_filenames(tmp_path: Path) -> None:
    """local/ and OpenRouter model ids carry / and : — invalid in filenames."""
    case = Case(id="c1", input={"prompt": "hello"}, expected={"x": 1})
    cr = CaseResult(
        case_id="c1",
        model="local/smollm2:135m",
        status="error",
        response=None,
        score=None,
        error="boom",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    p = write_case_diff(case, cr, tmp_path)
    assert p.exists()
    assert p.parent == tmp_path
    assert "/" not in p.name
    assert ":" not in p.name
    assert "local/smollm2:135m" in p.read_text(encoding="utf-8")
