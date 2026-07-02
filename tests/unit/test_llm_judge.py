"""LLM judge scorer — provider-agnostic resolution and scoring."""

from __future__ import annotations

import json
from typing import ClassVar, Literal

import pytest

from clean_evals.models import Case, ModelResponse
from clean_evals.scorers.llm_judge import LLMJudgeScorer


class _StubJudgeAdapter:
    provider: ClassVar[str] = "stub"

    def __init__(self, score: int = 8) -> None:
        self._score = score
        self.models_seen: list[str] = []

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
        self.models_seen.append(model)
        body = {"score": self._score, "reason": "stub"}
        return ModelResponse(
            content=json.dumps(body),
            parsed=body,
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
            cost_usd=0.0001,
        )


def _case() -> Case:
    return Case(id="c1", input={"prompt": "hi"}, expected={"text": "hello"})


def _response() -> ModelResponse:
    return ModelResponse(content="hello", latency_ms=1, cost_usd=0.0)


def test_injected_adapter_scores_normally() -> None:
    adapter = _StubJudgeAdapter(score=8)
    scorer = LLMJudgeScorer(judge_model="gpt-4o-mini-2024-07-18", adapter=adapter)
    result = scorer.score(_case(), _response())
    assert result.score == 0.8
    assert result.passed is True
    assert adapter.models_seen == ["gpt-4o-mini-2024-07-18"]


@pytest.mark.parametrize(
    ("judge_model", "expected_env"),
    [
        ("claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
        ("gpt-4o-mini-2024-07-18", "OPENAI_API_KEY"),
        ("gemini-2.0-flash-001", "GOOGLE_API_KEY"),
    ],
)
def test_skips_with_provider_specific_env_hint(judge_model: str, expected_env: str) -> None:
    # conftest strips all provider keys from the environment.
    scorer = LLMJudgeScorer(judge_model=judge_model)
    result = scorer.score(_case(), _response())
    assert result.score == 0.0
    assert result.notes is not None
    assert expected_env in result.notes


def test_unknown_model_prefix_skips_cleanly() -> None:
    scorer = LLMJudgeScorer(judge_model="mystery-model-3000")
    result = scorer.score(_case(), _response())
    assert result.score == 0.0
    assert result.notes is not None
    assert "mystery-model-3000" in result.notes


def test_from_config_reads_calibrated_standard() -> None:
    scorer = LLMJudgeScorer.from_config(
        {"judge_model": "gemini-2.0-flash-001", "rubric": "R", "pass_threshold": 0.5}
    )
    adapter = _StubJudgeAdapter(score=5)
    scorer._adapter = adapter  # inject after from_config
    result = scorer.score(_case(), _response())
    assert result.score == 0.5
    assert result.passed is True
    assert adapter.models_seen == ["gemini-2.0-flash-001"]


def test_calibrated_1_to_5_scale_normalizes_over_full_range() -> None:
    config = {"judge_model": "m", "rubric": "R", "judge_scale": 5, "judge_scale_min": 1}
    for raw, expected in [(5, 1.0), (3, 0.5), (1, 0.0)]:
        scorer = LLMJudgeScorer.from_config(config)
        scorer._adapter = _StubJudgeAdapter(score=raw)
        assert scorer.score(_case(), _response()).score == expected


def test_score_works_inside_a_running_event_loop() -> None:
    """The runner calls scorers from inside its own loop — this must not crash."""
    import asyncio

    scorer = LLMJudgeScorer(
        judge_model="claude-haiku-4-5-20251001", adapter=_StubJudgeAdapter(score=10)
    )

    async def in_loop() -> float:
        return scorer.score(_case(), _response()).score

    assert asyncio.run(in_loop()) == 1.0


def test_scores_reuse_one_event_loop_across_cases() -> None:
    """The judge loop persists: adapter connections stay valid case after case."""
    import asyncio

    loops: list[asyncio.AbstractEventLoop] = []

    class LoopRecordingAdapter(_StubJudgeAdapter):
        async def complete(self, *args, **kwargs):  # type: ignore[override]
            loops.append(asyncio.get_running_loop())
            return await super().complete(*args, **kwargs)

    scorer = LLMJudgeScorer(
        judge_model="claude-haiku-4-5-20251001", adapter=LoopRecordingAdapter(score=8)
    )

    async def run_like_the_runner() -> None:
        for _ in range(3):
            assert scorer.score(_case(), _response()).score == 0.8

    asyncio.run(run_like_the_runner())
    assert len(loops) == 3
    assert len({id(loop) for loop in loops}) == 1
