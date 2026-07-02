"""The eval runner.

The runner is async-native. It schedules every ``(case, model)`` pair as a
task, applies per-provider concurrency limits, retries transient failures
with exponential backoff (and ``Retry-After`` honour), applies best-effort
per-run + daily cost ceilings, and surfaces every result — successful or
otherwise — in the final ``RunResult``.

Failure is data, not exceptions. A single bad call never crashes the run.

Determinism is best-effort. With ``temperature=0`` and a seeded provider, the
same dataset + same models should produce byte-identical scored output. When
``temperature > 0`` the runner records ``deterministic=False`` on the run
result and the report carries a header warning.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import secrets
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Literal

from clean_evals._internal.events import EventSink, RunEvent, noop_sink, now
from clean_evals._internal.stats import mean, median, percentile
from clean_evals.errors import (
    AdapterError,
    CleanEvalsError,
    DailyCostLimitExceeded,
    ProviderTimeout,
    RateLimited,
    SchemaInvalidResponse,
    UnknownPlugin,
)
from clean_evals.models import (
    Case,
    CaseResult,
    Dataset,
    ModelResponse,
    ModelSummary,
    RunConfig,
    RunResult,
)
from clean_evals.pricing import effective_version, infer_provider
from clean_evals.prompting import AssembledRequest, assemble
from clean_evals.protocols import ModelAdapter, Scorer
from clean_evals.registry import adapters as adapter_registry
from clean_evals.registry import scorers as scorer_registry

_log = logging.getLogger(__name__)

_PROMPT_PLACEHOLDER = "{prompt}"

# Upper bound on a single retry sleep, even when the server's Retry-After
# asks for more.
_MAX_RETRY_WAIT_S = 120.0


class Runner:
    """Run a ``Dataset`` against a list of models.

    Args:
        adapters: Mapping from provider id to adapter instance. ``None`` (the
            default) builds a fresh adapter per provider on first use,
            instantiated from the entry-point registry.
        scorer_registry_obj: Custom registry. Most callers leave this ``None``
            and use the module-level singleton.
        prompt_template: How to render a case's input as a single prompt
            string. ``None`` (the default) JSON-serialises the input.
            Otherwise, must contain ``{prompt}`` exactly once. The literal
            string ``"{prompt}"`` is replaced with ``json.dumps(case.input)``.
        event_sink: Optional progress sink. Default no-op for headless runs.
        daily_cost_so_far_usd: How much was spent today before this run
            started. ``None`` treats prior spend as $0 — callers with
            storage access (the CLI, web, and queue paths) pass the
            persisted total for today. Only persisted runs leave a cost
            trail, so the daily limit is best-effort.

    Example:
        >>> import asyncio
        >>> from clean_evals import Dataset, Runner, RunConfig
        >>> ds = Dataset(  # doctest: +SKIP
        ...     name="hello", version="v1", scorer="exact_match", cases=[],
        ... )
        >>> runner = Runner()  # doctest: +SKIP
        >>> result = asyncio.run(runner.run(  # doctest: +SKIP
        ...     ds, RunConfig(models=["gpt-4o-mini-2024-07-18"]),
        ... ))
    """

    def __init__(
        self,
        *,
        adapters: dict[str, ModelAdapter] | None = None,
        scorer_registry_obj: Any = None,
        prompt_template: str | None = None,
        event_sink: EventSink | None = None,
        daily_cost_so_far_usd: float | None = None,
    ) -> None:
        self._adapters: dict[str, ModelAdapter] = adapters or {}
        self._owned_providers: set[str] = set()
        self._scorer_registry = scorer_registry_obj or scorer_registry
        self._prompt_template = prompt_template
        if prompt_template is not None and prompt_template.count(_PROMPT_PLACEHOLDER) != 1:
            raise ValueError(
                f"prompt_template must contain exactly one {_PROMPT_PLACEHOLDER!r} marker"
            )
        self._event_sink = event_sink or noop_sink
        self._daily_cost_so_far = daily_cost_so_far_usd

    # ------------------------------------------------------------------
    # Sync facade
    # ------------------------------------------------------------------

    def run_sync(self, dataset: Dataset, config: RunConfig) -> RunResult:
        """Synchronous wrapper. Spins up a fresh event loop and blocks.

        Adapters the runner instantiated itself are closed before the loop
        is torn down (their HTTP clients are bound to it). Explicitly
        injected adapters stay open — the caller owns their lifecycle.
        """

        async def _run_and_close() -> RunResult:
            try:
                return await self.run(dataset, config)
            finally:
                await self.aclose()

        return asyncio.run(_run_and_close())

    async def aclose(self) -> None:
        """Close HTTP clients of adapters this runner created lazily."""
        for provider in sorted(self._owned_providers):
            adapter = self._adapters.pop(provider, None)
            closer = getattr(adapter, "aclose", None)
            if closer is None:
                continue
            try:
                await closer()
            except Exception as exc:
                _log.warning("closing %s adapter raised %r; ignoring", provider, exc)
        self._owned_providers.clear()

    # ------------------------------------------------------------------
    # Async core
    # ------------------------------------------------------------------

    async def run(self, dataset: Dataset, config: RunConfig) -> RunResult:
        """Run ``dataset`` against ``config.models``."""
        run_id = _new_run_id()
        started_at = now()
        notes: list[str] = []

        self._check_daily_cost_limit()

        scorer = self._scorer_registry.build(dataset.scorer, dataset.scorer_config)

        deterministic = config.temperature == 0.0
        if not deterministic:
            notes.append(f"temperature={config.temperature} > 0; results are not deterministic.")

        # Group concurrency by provider. Empty cap = uncapped.
        per_provider_semaphores: dict[str, asyncio.Semaphore | None] = {}
        for provider, cap in config.concurrency.items():
            per_provider_semaphores[provider] = asyncio.Semaphore(max(1, cap))

        cost_state = _CostState(max_cost=config.max_cost_usd)

        self._emit(
            RunEvent(
                type="run.started",
                run_id=run_id,
                at=now(),
                payload={
                    "dataset": dataset.name,
                    "dataset_version": dataset.version,
                    "models": list(config.models),
                    "case_count": len(dataset.cases),
                },
            )
        )

        # Schedule (case, model) tasks.
        case_results: list[CaseResult] = []
        sem_lookup: dict[str, asyncio.Semaphore | None] = dict(per_provider_semaphores)

        async def run_one(case: Case, model: str) -> CaseResult:
            try:
                provider = self._resolve_provider(model)
            except ValueError as exc:
                # Failure is data: an unrecognised model id fails its own
                # cases instead of crashing the whole run.
                return _failed_case(case.id, model, status="error", reason=str(exc))
            sem = sem_lookup.get(provider)
            if sem is not None:
                async with sem:
                    return await self._run_single(
                        run_id=run_id,
                        case=case,
                        model=model,
                        provider=provider,
                        config=config,
                        scorer=scorer,
                        dataset=dataset,
                        cost_state=cost_state,
                    )
            return await self._run_single(
                run_id=run_id,
                case=case,
                model=model,
                provider=provider,
                config=config,
                scorer=scorer,
                dataset=dataset,
                cost_state=cost_state,
            )

        tasks = [
            asyncio.create_task(run_one(case, model))
            for case in dataset.cases
            for model in config.models
        ]
        try:
            for finished in asyncio.as_completed(tasks):
                case_results.append(await finished)
        finally:
            # Cancel anything that's left if we were cancelled externally.
            for t in tasks:
                if not t.done():
                    t.cancel()

        if cost_state.aborted:
            notes.append(f"Run aborted: cost ceiling ${config.max_cost_usd:.2f} exceeded.")

        finished_at = now()

        summary = _summarise(case_results, config.models)

        result = RunResult(
            run_id=run_id,
            dataset=dataset.name,
            dataset_version=dataset.version,
            config=config,
            cases=sorted(case_results, key=lambda r: (r.case_id, r.model)),
            summary=summary,
            started_at=started_at,
            finished_at=finished_at,
            pricing_version=effective_version(),
            deterministic=deterministic,
            notes=notes,
        )

        self._emit(
            RunEvent(
                type="run.finished",
                run_id=run_id,
                at=finished_at,
                payload={
                    "summary": {m: s.model_dump(mode="json") for m, s in summary.items()},
                    "aborted": cost_state.aborted,
                },
            )
        )
        return result

    # ------------------------------------------------------------------
    # Single-call execution path
    # ------------------------------------------------------------------

    async def _run_single(
        self,
        *,
        run_id: str,
        case: Case,
        model: str,
        provider: str,
        config: RunConfig,
        scorer: Scorer,
        dataset: Dataset,
        cost_state: _CostState,
    ) -> CaseResult:
        if cost_state.aborted:
            return _failed_case(
                case.id,
                model,
                status="aborted_cost",
                reason="cost ceiling reached before scheduling",
            )

        self._emit(
            RunEvent(
                type="run.case_started",
                run_id=run_id,
                at=now(),
                payload={"case_id": case.id, "model": model},
            )
        )

        try:
            adapter = await self._get_adapter(provider)
        except UnknownPlugin as exc:
            # Failure is data: a provider with no registered adapter fails
            # its own cases instead of crashing the run.
            return _failed_case(case.id, model, status="error", reason=str(exc))
        request = self._assemble_request(case, dataset)
        started_at = now()

        response: ModelResponse | None = None
        status: str = "ok"
        error: str | None = None

        for attempt in range(config.retries + 1):
            try:
                params = config.model_params.get(model)
                response = await adapter.complete(
                    prompt=request.user,
                    model=model,
                    temperature=(
                        params.temperature
                        if params is not None and params.temperature is not None
                        else config.temperature
                    ),
                    seed=config.seed,
                    timeout_s=config.timeout_s,
                    response_format=_response_format_for(dataset),
                    system=request.system,
                    reasoning_effort=params.reasoning_effort if params else None,
                    max_output_tokens=params.max_output_tokens if params else None,
                )
                break
            except RateLimited as exc:
                if attempt >= config.retries:
                    status, error = "error", f"rate-limited: {exc}"
                    break
                wait = exc.retry_after_s if exc.retry_after_s is not None else _backoff(attempt)
                # Honour Retry-After, but never let a hostile or garbled
                # header stall a worker indefinitely.
                wait = min(wait, _MAX_RETRY_WAIT_S)
                _log.info(
                    "rate-limited %s on %s/%s; sleeping %.1fs (attempt %d/%d)",
                    provider,
                    case.id,
                    model,
                    wait,
                    attempt + 1,
                    config.retries + 1,
                )
                await asyncio.sleep(wait)
            except ProviderTimeout as exc:
                if attempt >= config.retries:
                    status, error = "timeout", f"timeout: {exc}"
                    break
                await asyncio.sleep(_backoff(attempt))
            except SchemaInvalidResponse as exc:
                status, error = "schema_invalid", str(exc)
                break
            except AdapterError as exc:
                if attempt >= config.retries:
                    status, error = "error", f"adapter error: {exc}"
                    break
                await asyncio.sleep(_backoff(attempt))
            except Exception as exc:
                status, error = "error", f"unexpected: {exc!r}"
                break

        finished_at = now()

        score = None
        if status == "ok" and response is not None:
            cost_state.add(response.cost_usd)
            try:
                score = scorer.score(case, response)
            except Exception as exc:
                status, error = "error", f"scorer raised: {exc!r}"
                score = None

        if cost_state.exceeded() and not cost_state.aborted:
            cost_state.aborted = True
            self._emit(
                RunEvent(
                    type="run.cost_warning",
                    run_id=run_id,
                    at=now(),
                    payload={"spend_usd": cost_state.spend, "limit_usd": cost_state.max_cost},
                )
            )

        result = CaseResult(
            case_id=case.id,
            model=model,
            status=status,  # type: ignore[arg-type]
            response=response if status == "ok" else None,
            score=score,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
        )

        self._emit(
            RunEvent(
                type="run.case_finished",
                run_id=run_id,
                at=finished_at,
                payload={
                    "case_id": case.id,
                    "model": model,
                    "status": status,
                    "score": score.score if score is not None else None,
                    "cost_usd": response.cost_usd if response is not None else 0.0,
                },
            )
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_adapter(self, provider: str) -> ModelAdapter:
        if provider in self._adapters:
            return self._adapters[provider]
        cls = adapter_registry.get(provider)
        adapter = cls()
        self._adapters[provider] = adapter
        self._owned_providers.add(provider)
        return adapter

    def _resolve_provider(self, model: str) -> str:
        """Infer the provider from the model id's prefix.

        Explicitly injected adapters are honoured downstream: when the
        inferred provider matches a key in ``self._adapters``,
        ``_get_adapter`` returns that instance instead of building one.

        Raises:
            ValueError: When no known prefix matches.
        """
        return infer_provider(model)

    def _assemble_request(self, case: Case, dataset: Dataset) -> AssembledRequest:
        if dataset.request_shape == "templated":
            return assemble(
                request_shape=dataset.request_shape,
                system_prompt=dataset.system_prompt,
                shared_context=dataset.shared_context,
                user_template=dataset.user_template,
                case_input=case.input,
            )

        # Raw shape — legacy path: single field (or JSON) plus the optional
        # {prompt} wrapper template from the constructor or scorer_config.
        import json as _json

        body = case.input.get("prompt") if isinstance(case.input.get("prompt"), str) else None
        if body is None:
            body = _json.dumps(case.input, ensure_ascii=False, indent=2)
        if self._prompt_template is None:
            tpl = dataset.scorer_config.get("prompt_template")
            if isinstance(tpl, str) and _PROMPT_PLACEHOLDER in tpl:
                return AssembledRequest(system=None, user=tpl.replace(_PROMPT_PLACEHOLDER, body))
            return AssembledRequest(system=None, user=body)
        return AssembledRequest(
            system=None, user=self._prompt_template.replace(_PROMPT_PLACEHOLDER, body)
        )

    def _check_daily_cost_limit(self) -> None:
        env_val = os.environ.get("CLEAN_EVALS_DAILY_COST_LIMIT_USD")
        if not env_val:
            return
        try:
            limit = float(env_val)
        except ValueError as exc:
            raise CleanEvalsError(
                f"CLEAN_EVALS_DAILY_COST_LIMIT_USD={env_val!r} is not a number"
            ) from exc
        spent_today = self._daily_cost_so_far if self._daily_cost_so_far is not None else 0.0
        if spent_today >= limit:
            raise DailyCostLimitExceeded(
                f"Today's spend ${spent_today:.2f} >= daily limit ${limit:.2f}"
            )

    def _emit(self, event: RunEvent) -> None:
        try:
            self._event_sink(event)
        except Exception as exc:
            _log.warning("event sink raised %r; ignoring", exc)


# ---------------------------------------------------------------------------
# Internal helpers (file-private)
# ---------------------------------------------------------------------------


class _CostState:
    """Tracks cumulative spend during a run."""

    def __init__(self, max_cost: float) -> None:
        self.max_cost = max_cost
        self.spend = 0.0
        self.aborted = False

    def add(self, amount: float) -> None:
        self.spend += max(0.0, amount)

    def exceeded(self) -> bool:
        return self.spend >= self.max_cost


def _new_run_id() -> str:
    """Generate a sortable, opaque run id.

    Format: ``r_{timestamp}_{random}``. Lexically sorted prefix sorts by
    creation time, which is convenient for storage queries.
    """
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"r_{ts}_{secrets.token_hex(4)}"


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter.

    1.0 * 2 ** attempt, capped at 30 seconds. Adapter ``Retry-After`` always
    wins over this when present.
    """
    base = min(30.0, math.pow(2.0, attempt))
    jitter = secrets.randbelow(1000) / 1000.0
    return base + jitter


def _response_format_for(dataset: Dataset) -> Literal["text", "json"]:
    """Pull the desired response_format out of dataset.scorer_config."""
    fmt = dataset.scorer_config.get("response_format")
    if fmt == "text":
        return "text"
    if fmt == "json":
        return "json"
    # Default: structured scorers want JSON, exact_match wants text.
    if dataset.scorer == "json_field_match":
        return "json"
    return "text"


def _failed_case(
    case_id: str, model: str, *, status: Literal["aborted_cost", "error"], reason: str
) -> CaseResult:
    """A synthetic result for a case that never reached the provider."""
    ts = now()
    return CaseResult(
        case_id=case_id,
        model=model,
        status=status,
        response=None,
        score=None,
        error=reason,
        started_at=ts,
        finished_at=ts,
    )


def _summarise(case_results: list[CaseResult], models: list[str]) -> dict[str, ModelSummary]:
    """Build the per-model leaderboard."""
    grouped: dict[str, list[CaseResult]] = defaultdict(list)
    for cr in case_results:
        grouped[cr.model].append(cr)

    summary: dict[str, ModelSummary] = {}
    for model in models:
        rows = grouped.get(model, [])
        scores = [r.score.score for r in rows if r.score is not None]
        passed = sum(1 for r in rows if r.score is not None and r.score.passed)
        latencies = [
            r.response.latency_ms for r in rows if r.response is not None and r.status == "ok"
        ]
        errors = sum(1 for r in rows if r.status != "ok")
        cost = sum(r.response.cost_usd for r in rows if r.response is not None)
        summary[model] = ModelSummary(
            model=model,
            cases_run=len(rows),
            cases_passed=passed,
            score_mean=mean(scores),
            score_p50=median(scores),
            latency_p95_ms=int(percentile(latencies, 95)) if latencies else 0,
            error_rate=(errors / len(rows)) if rows else 0.0,
            total_cost_usd=cost,
            cost_per_correct_usd=(cost / passed) if passed else None,
            pricing_version=effective_version(),
        )
    return summary
