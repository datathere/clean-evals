"""Stage 2 — generate candidate outputs (docs/docs/flow.md).

Sends every case to every candidate model once and stores the outputs so
the reviewer can pick the golden answer from real material. Nothing is
scored here; there is nothing to score against yet.

Runs in-process — a self-hosted install needs no queue for this. The web
layer calls :func:`generate_candidates` from a background task and polls
:class:`GenerationJob` for progress; the CLI awaits it directly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from clean_evals import jobs
from clean_evals.errors import CostCeilingExceeded
from clean_evals.models import ModelParams
from clean_evals.pricing import infer_provider
from clean_evals.prompting import assemble
from clean_evals.protocols import ModelAdapter
from clean_evals.registry import adapters as adapter_registry
from clean_evals.storage.db import CandidateOutputRow, CaseRow, DatasetRow

_log = logging.getLogger(__name__)


@dataclass
class GenerationJob:
    """Progress of one candidate-generation pass.

    Mirrored to the ``jobs`` table (``job_id``) so status survives server
    restarts and is visible across worker processes; the API polls the
    table, never this object.
    """

    dataset_id: int
    models: list[str]
    job_id: int | None = None
    total: int = 0
    done: int = 0
    errors: int = 0
    cost_usd: float = 0.0
    status: str = "running"  # running|done|error|aborted_cost
    detail: str | None = None


@dataclass
class _CostState:
    limit: float
    spent: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def add(self, amount: float) -> None:
        async with self.lock:
            self.spent += amount
            if self.spent > self.limit:
                raise CostCeilingExceeded(
                    f"Candidate generation cost ${self.spent:.2f} exceeded "
                    f"ceiling ${self.limit:.2f}"
                )


async def generate_candidates(
    session_factory: sessionmaker[Session],
    dataset_id: int,
    models: list[str],
    *,
    temperature: float = 0.0,
    seed: int | None = 42,
    timeout_s: float = 120.0,
    max_cost_usd: float = 5.0,
    concurrency: int = 4,
    adapters: dict[str, ModelAdapter] | None = None,
    model_params: dict[str, ModelParams] | None = None,
    job: GenerationJob | None = None,
) -> GenerationJob:
    """Generate one output per (case, model). Existing pairs are replaced.

    Raises:
        ValueError: When the dataset does not exist or has no cases.
    """
    with session_factory() as session:
        ds = session.get(DatasetRow, dataset_id)
        if ds is None:
            raise ValueError(f"Dataset id={dataset_id} not found")
        request_shape = ds.request_shape
        system_prompt = ds.system_prompt
        shared_context = ds.shared_context
        user_template = ds.user_template
        wants_json = ds.scorer == "json_field_match"
        cases = [
            (c.id, c.case_id_external, dict(c.input_jsonb or {}))
            for c in session.execute(
                select(CaseRow).where(CaseRow.dataset_id == dataset_id)
            ).scalars()
        ]
    if not cases:
        raise ValueError(f"Dataset id={dataset_id} has no cases")

    if job is None:
        job = GenerationJob(dataset_id=dataset_id, models=list(models))
    job.total = len(cases) * len(models)
    if job.job_id is None:
        job.job_id = jobs.create(
            session_factory, kind=jobs.GENERATION, dataset_id=dataset_id, total=job.total
        )
    else:
        jobs.update(session_factory, job.job_id, total=job.total)

    def flush() -> None:
        assert job is not None
        assert job.job_id is not None
        jobs.update(
            session_factory,
            job.job_id,
            status=job.status,
            done=job.done,
            errors=job.errors,
            cost_usd=job.cost_usd,
            detail=job.detail,
        )

    adapter_cache: dict[str, ModelAdapter] = dict(adapters or {})

    def adapter_for(model: str) -> ModelAdapter:
        provider = infer_provider(model)
        if provider not in adapter_cache:
            adapter_cache[provider] = adapter_registry.get(provider)()
        return adapter_cache[provider]

    cost = _CostState(limit=max_cost_usd)
    sem = asyncio.Semaphore(max(1, concurrency))
    results: list[dict[str, Any]] = []

    async def one(case_pk: int, case_ext: str, case_input: dict[str, Any], model: str) -> None:
        row: dict[str, Any] = {"case_id": case_pk, "model": model}
        try:
            request = assemble(
                request_shape=request_shape,
                system_prompt=system_prompt,
                shared_context=shared_context,
                user_template=user_template,
                case_input=case_input,
            )
            params = (model_params or {}).get(model)
            # Passed only when present — see the same pattern in runner.py.
            extra: dict[str, Any] = {"history": request.history} if request.history else {}
            async with sem:
                response = await adapter_for(model).complete(
                    prompt=request.user,
                    model=model,
                    temperature=(
                        params.temperature
                        if params is not None and params.temperature is not None
                        else temperature
                    ),
                    seed=seed,
                    timeout_s=timeout_s,
                    response_format="json" if wants_json else "text",
                    system=request.system,
                    reasoning_effort=params.reasoning_effort if params else None,
                    max_output_tokens=params.max_output_tokens if params else None,
                    **extra,
                )
            await cost.add(response.cost_usd)
            row.update(
                content=response.content,
                parsed_jsonb=response.parsed,
                status="ok",
                error=None,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                latency_ms=response.latency_ms,
                cost_usd=response.cost_usd,
            )
            job.cost_usd = cost.spent
        except CostCeilingExceeded:
            job.status = "aborted_cost"
            raise
        except Exception as exc:
            _log.warning("candidate %s/%s failed: %s", case_ext, model, exc)
            job.errors += 1
            row.update(
                content="",
                parsed_jsonb=None,
                status="error",
                error=str(exc),
                tokens_in=None,
                tokens_out=None,
                latency_ms=None,
                cost_usd=None,
            )
        results.append(row)
        job.done += 1
        flush()

    tasks = [
        asyncio.create_task(one(case_pk, case_ext, case_input, model))
        for case_pk, case_ext, case_input in cases
        for model in models
    ]
    try:
        await asyncio.gather(*tasks)
    except CostCeilingExceeded as exc:
        for t in tasks:
            if not t.done():
                t.cancel()
        job.detail = str(exc)
    except Exception as exc:
        job.status = "error"
        job.detail = str(exc)
        raise
    finally:
        _persist(session_factory, results)
        if job.status == "running":
            job.status = "done"
        flush()

    return job


def _persist(session_factory: sessionmaker[Session], results: list[dict[str, Any]]) -> None:
    if not results:
        return
    with session_factory() as session:
        for row in results:
            existing = session.execute(
                select(CandidateOutputRow).where(
                    CandidateOutputRow.case_id == row["case_id"],
                    CandidateOutputRow.model == row["model"],
                )
            ).scalar_one_or_none()
            if existing is not None:
                session.delete(existing)
                session.flush()
            session.add(CandidateOutputRow(**row))
        session.commit()
