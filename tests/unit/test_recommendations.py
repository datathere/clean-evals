"""Tests for the three recommendation cards math."""

from __future__ import annotations

from datetime import UTC, datetime

from clean_evals._internal.recommendations import (
    DEFAULT_PP_THRESHOLD,
    all_three,
    fmt_usd,
    lowest_cost,
    max_accuracy,
    price_performance,
)
from clean_evals.models import ModelSummary, RunConfig, RunResult


def _result(*, summary: dict[str, ModelSummary]) -> RunResult:
    return RunResult(
        run_id="r_test",
        dataset="d",
        dataset_version="v1",
        config=RunConfig(models=list(summary)),
        cases=[],
        summary=summary,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        pricing_version="2026.04",
        deterministic=True,
    )


def _row(model: str, score: float, cost: float, passed: int = 10) -> ModelSummary:
    return ModelSummary(
        model=model,
        cases_run=10,
        cases_passed=passed,
        score_mean=score,
        score_p50=score,
        latency_p95_ms=1000,
        error_rate=0.0,
        total_cost_usd=cost,
        cost_per_correct_usd=cost / passed if passed else None,
        pricing_version="2026.04",
    )


def test_max_accuracy_picks_highest_score() -> None:
    result = _result(
        summary={
            "a": _row("a", 0.91, 0.5),
            "b": _row("b", 0.88, 0.4),
        }
    )
    rec = max_accuracy(result)
    assert rec.model == "a"
    assert "0.910" in rec.rationale


def test_max_accuracy_tie_break_on_cost() -> None:
    result = _result(
        summary={
            "a": _row("a", 0.9, 0.5),
            "b": _row("b", 0.9, 0.3),
        }
    )
    rec = max_accuracy(result)
    assert rec.model == "b"


def test_lowest_cost() -> None:
    result = _result(
        summary={
            "a": _row("a", 0.9, 0.5),
            "b": _row("b", 0.7, 0.05),
        }
    )
    rec = lowest_cost(result)
    assert rec.model == "b"
    assert "$0.05" in rec.rationale


def test_fmt_usd_keeps_small_costs_readable() -> None:
    assert fmt_usd(0) == "$0"
    assert fmt_usd(1.5) == "$1.50"
    assert fmt_usd(0.05) == "$0.05"
    assert fmt_usd(0.00055) == "$0.00055"
    assert fmt_usd(0.0001035) == "$0.00010"
    assert fmt_usd(0.000010035) == "$0.000010"


def test_price_performance_filters_below_threshold() -> None:
    result = _result(
        summary={
            "claude": _row("claude", 0.91, 0.42),
            "gpt-4o": _row("gpt-4o", 0.88, 0.39),
            "mini": _row("mini", 0.74, 0.03),
        }
    )
    rec = price_performance(result, threshold=DEFAULT_PP_THRESHOLD)
    # mini is excluded; gpt-4o has lower cost-per-pt -> $0.39 / 88 vs claude $0.42 / 91
    # gpt-4o: 0.39 / 88 = 0.00443; claude: 0.42 / 91.2 = 0.00461 -> gpt-4o wins
    assert rec.model == "gpt-4o"
    assert "Below threshold" in rec.rationale
    assert "mini" in rec.rationale


def test_price_performance_no_qualifying_models() -> None:
    result = _result(
        summary={
            "a": _row("a", 0.5, 0.10),
            "b": _row("b", 0.6, 0.20),
        }
    )
    rec = price_performance(result)
    assert rec.model is None
    assert "No models" in rec.rationale


def test_all_three_returns_three_keys() -> None:
    result = _result(summary={"a": _row("a", 0.9, 0.5)})
    out = all_three(result)
    assert set(out.keys()) == {"max_accuracy", "price_performance", "lowest_cost"}
