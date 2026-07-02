"""End-to-end runner tests with a fake adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

import pytest

from clean_evals.errors import RateLimited
from clean_evals.models import Case, Dataset, ModelResponse, RunConfig
from clean_evals.runner import Runner


class _FakeAdapter:
    provider: ClassVar[str] = "anthropic"

    def __init__(
        self,
        *,
        outputs: dict[str, dict[str, Any]] | None = None,
        rate_limit_first: bool = False,
        cost: float = 0.001,
    ) -> None:
        self._outputs = outputs or {}
        self._rate_limit_first = rate_limit_first
        self._cost = cost
        self._called: dict[str, int] = {}

    async def complete(
        self,
        prompt: str,
        model: str,
        *,
        temperature: float,
        seed: int | None,
        timeout_s: float,
        response_format: Literal["text", "json"] = "text",
        system: str | None = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelResponse:
        key = f"{model}:{prompt[:40]}"
        self._called[key] = self._called.get(key, 0) + 1
        if self._rate_limit_first and self._called[key] == 1:
            raise RateLimited("simulated 429", retry_after_s=0.001)
        text = self._outputs.get(prompt, {}).get(model, "default")
        return ModelResponse(content=text, latency_ms=10, cost_usd=self._cost)


def _ds(case_count: int = 2) -> Dataset:
    cases = [
        Case(id=f"c{i}", input={"prompt": f"p{i}"}, expected={"text": f"want{i}"})
        for i in range(case_count)
    ]
    return Dataset(
        name="d",
        version="v1",
        scorer="exact_match",
        scorer_config={},
        cases=cases,
    )


def test_runner_basic_smoke() -> None:
    model = "claude-3-5-sonnet-20241022"
    fake = _FakeAdapter(
        outputs={"p0": {model: "want0"}, "p1": {model: "want1"}},
    )
    runner = Runner(adapters={"anthropic": fake})
    result = runner.run_sync(
        _ds(),
        RunConfig(models=[model], retries=0, max_cost_usd=10),
    )
    summary = result.summary[model]
    assert summary.cases_run == 2
    # Both adapter outputs match expected{text: ...} in the dataset.
    assert summary.score_mean > 0


def test_runner_records_failure_without_crashing() -> None:
    class BoomAdapter(_FakeAdapter):
        async def complete(self, *args: Any, **kwargs: Any) -> ModelResponse:  # type: ignore[override]
            raise RuntimeError("boom")

    runner = Runner(adapters={"anthropic": BoomAdapter()})
    result = runner.run_sync(
        _ds(),
        RunConfig(models=["claude-3-5-sonnet-20241022"], retries=0, max_cost_usd=10),
    )
    assert all(c.status == "error" for c in result.cases)
    assert result.summary["claude-3-5-sonnet-20241022"].error_rate == 1.0


def test_runner_retries_on_rate_limit() -> None:
    fake = _FakeAdapter(rate_limit_first=True)
    runner = Runner(adapters={"anthropic": fake})
    result = runner.run_sync(
        _ds(case_count=1),
        RunConfig(models=["claude-3-5-sonnet-20241022"], retries=2, max_cost_usd=10),
    )
    # After retry, the call succeeds.
    assert result.cases[0].status == "ok"


def test_runner_cost_ceiling_aborts() -> None:
    fake = _FakeAdapter(cost=10.0)
    runner = Runner(adapters={"anthropic": fake})
    result = runner.run_sync(
        _ds(case_count=4),
        RunConfig(models=["claude-3-5-sonnet-20241022"], max_cost_usd=5.0, retries=0),
    )
    statuses = [c.status for c in result.cases]
    assert "aborted_cost" in statuses


def test_runner_marks_non_deterministic() -> None:
    fake = _FakeAdapter()
    runner = Runner(adapters={"anthropic": fake})
    result = runner.run_sync(
        _ds(case_count=1),
        RunConfig(
            models=["claude-3-5-sonnet-20241022"],
            temperature=0.7,
            retries=0,
            max_cost_usd=10,
        ),
    )
    assert result.deterministic is False
    assert any("temperature" in n for n in result.notes)


def test_runner_async_works_under_running_loop() -> None:
    """Sanity check that the async API integrates with arbitrary loops."""

    fake = _FakeAdapter(outputs={"p0": {"m": "want0"}})
    runner = Runner(adapters={"anthropic": fake})

    async def inner() -> None:
        result = await runner.run(
            _ds(case_count=1),
            RunConfig(models=["claude-3-5-sonnet-20241022"], retries=0, max_cost_usd=10),
        )
        assert result.cases[0].case_id == "c0"

    asyncio.run(inner())


def test_runner_emits_events() -> None:
    captured: list[str] = []
    fake = _FakeAdapter()
    runner = Runner(
        adapters={"anthropic": fake},
        event_sink=lambda e: captured.append(e.type),
    )
    runner.run_sync(
        _ds(case_count=1),
        RunConfig(models=["claude-3-5-sonnet-20241022"], retries=0, max_cost_usd=10),
    )
    assert "run.started" in captured
    assert "run.case_started" in captured
    assert "run.case_finished" in captured
    assert "run.finished" in captured


def test_runner_daily_cost_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLEAN_EVALS_DAILY_COST_LIMIT_USD", "0.01")
    runner = Runner(daily_cost_so_far_usd=0.05)
    with pytest.raises(Exception):  # noqa: B017 — DailyCostLimitExceeded -> CleanEvalsError
        runner.run_sync(
            _ds(case_count=1),
            RunConfig(models=["claude-3-5-sonnet-20241022"], retries=0, max_cost_usd=10),
        )


def test_dataclass_timestamps_are_utc() -> None:
    fake = _FakeAdapter()
    runner = Runner(adapters={"anthropic": fake})
    started = datetime.now(UTC)
    result = runner.run_sync(
        _ds(case_count=1),
        RunConfig(models=["claude-3-5-sonnet-20241022"], retries=0, max_cost_usd=10),
    )
    finished = datetime.now(UTC)
    assert started <= result.started_at <= result.finished_at <= finished
