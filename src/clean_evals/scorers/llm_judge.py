"""LLM-as-a-judge scorer.

Provider-agnostic: the judge model can be any snapshot from any registered
adapter — the provider is inferred from the model id and resolved through
the adapter registry, exactly like candidate models. Default judge is
``claude-haiku-4-5-20251001`` — small, fast, and cheap enough that judge
cost rarely dominates eval cost.

The judge is invoked synchronously. For datasets large enough that judge
cost is a concern, the runner already shows judge spend in the cost
breakdown — surface it explicitly when scaling.

Configuration:

.. code-block:: yaml

    scorer: llm_judge
    scorer_config:
      judge_model: gpt-4o-mini-2024-07-18   # any connected provider
      rubric: |
        Score the response 0-10 on faithfulness to the expected output.
        Return JSON: {"score": <int>, "reason": "<one sentence>"}.
      pass_threshold: 0.7

Judge calibration (docs/docs/flow.md, stage 4) writes ``judge_model`` and
a few-shot ``rubric`` into ``scorer_config``, so calibrated datasets are
scored by the standard the reviewer signed off on.

Judge output is parsed as JSON ``{"score": int|float, "reason": str}``;
``score`` is normalised to 0.0–1.0 by dividing by 10.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import weakref
from typing import Any, ClassVar

from clean_evals.models import Case, ModelResponse, ScoreResult
from clean_evals.pricing import PROVIDER_ENV_VARS, infer_provider
from clean_evals.protocols import ModelAdapter

_DEFAULT_JUDGE = "claude-haiku-4-5-20251001"

_DEFAULT_RUBRIC = """\
You are evaluating an AI assistant's response.

Score the response on a 0-10 scale based on how well it matches the EXPECTED
output. Use the full range. A perfect match is 10; a clearly wrong answer
is 0; partial credit is allowed for partially correct responses.

Return ONLY a JSON object: {"score": <integer 0-10>, "reason": "<one sentence>"}.
"""

_PROMPT_TEMPLATE = """\
{rubric}

INPUT:
{input}

EXPECTED:
{expected}

ACTUAL:
{actual}

Return only the JSON object.
"""


class LLMJudgeScorer:
    name: ClassVar[str] = "llm_judge"

    def __init__(
        self,
        *,
        judge_model: str = _DEFAULT_JUDGE,
        rubric: str = _DEFAULT_RUBRIC,
        pass_threshold: float = 0.7,
        adapter: ModelAdapter | None = None,
        timeout_s: float = 30.0,
        judge_scale: float = 10.0,
        judge_scale_min: float = 0.0,
    ) -> None:
        self._judge_model = judge_model
        self._rubric = rubric
        self._pass_threshold = pass_threshold
        self._adapter = adapter
        self._timeout_s = timeout_s
        self._judge_scale = judge_scale
        self._judge_scale_min = judge_scale_min
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> LLMJudgeScorer:
        return cls(
            judge_model=str(config.get("judge_model") or _DEFAULT_JUDGE),
            rubric=str(config.get("rubric") or _DEFAULT_RUBRIC),
            pass_threshold=float(config.get("pass_threshold", 0.7)),
            timeout_s=float(config.get("timeout_s", 30.0)),
            # Calibrated rubrics (stage 4) score 1-5 to match human ratings
            # and write judge_scale/judge_scale_min; the default rubric is 0-10.
            judge_scale=float(config.get("judge_scale", 10.0)),
            judge_scale_min=float(config.get("judge_scale_min", 0.0)),
        )

    def _skip_reason(self) -> str | None:
        """A reason the judge cannot run, or ``None`` when it can."""
        if self._adapter is not None:
            return None
        try:
            provider = infer_provider(self._judge_model)
        except ValueError as exc:
            return str(exc)
        env_var = PROVIDER_ENV_VARS.get(provider)
        if env_var and not os.environ.get(env_var, "").strip():
            return f"{env_var} not set; judge skipped"
        return None

    def _resolve_adapter(self) -> ModelAdapter:
        if self._adapter is None:
            from clean_evals.registry import adapters as adapter_registry

            provider = infer_provider(self._judge_model)
            self._adapter = adapter_registry.get(provider)()
        return self._adapter

    def _judge_loop(self) -> asyncio.AbstractEventLoop:
        # One persistent loop for the scorer's lifetime. The adapter's HTTP
        # client binds its connections to the loop of the first call; a
        # fresh loop per case would leave them pointing at a closed loop
        # ("Event loop is closed") from the second case on.
        with self._loop_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(target=loop.run_forever, daemon=True, name="llm-judge")
                thread.start()
                self._loop = loop
                weakref.finalize(self, loop.call_soon_threadsafe, loop.stop)
        return self._loop

    def score(self, case: Case, response: ModelResponse) -> ScoreResult:
        # Sync facade over an async adapter call. Judge calls always run on
        # the scorer's private loop; the runner invokes scorers from inside
        # its own event loop, where asyncio.run would be illegal anyway.
        skip = self._skip_reason()
        if skip is not None:
            return ScoreResult(score=0.0, passed=False, breakdown={}, notes=skip)
        future = asyncio.run_coroutine_threadsafe(self._judge(case, response), self._judge_loop())
        return future.result(timeout=self._timeout_s * 2)

    async def _judge(self, case: Case, response: ModelResponse) -> ScoreResult:
        prompt = _PROMPT_TEMPLATE.format(
            rubric=self._rubric.strip(),
            input=json.dumps(case.input, ensure_ascii=False, indent=2),
            expected=json.dumps(case.expected or {}, ensure_ascii=False, indent=2),
            actual=response.content,
        )
        judge_response = await self._resolve_adapter().complete(
            prompt=prompt,
            model=self._judge_model,
            temperature=0.0,
            seed=0,
            timeout_s=self._timeout_s,
            response_format="json",
        )
        parsed = judge_response.parsed or {}
        try:
            raw_score = float(parsed.get("score", 0))
        except (TypeError, ValueError):
            return ScoreResult(
                score=0.0, passed=False, breakdown={}, notes="judge returned non-numeric score"
            )
        span = self._judge_scale - self._judge_scale_min
        normalized = (raw_score - self._judge_scale_min) / span if span > 0 else 0.0
        score = max(0.0, min(1.0, normalized))
        reason = str(parsed.get("reason", ""))
        return ScoreResult(
            score=score,
            passed=score >= self._pass_threshold,
            breakdown={"judge": score},
            notes=reason or None,
        )
