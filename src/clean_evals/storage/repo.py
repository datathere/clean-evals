"""Repository helpers for converting between domain models and ORM rows.

Keeps the rest of the codebase free of session/Engine plumbing. Used by:

- The CLI when persisting ``RunResult`` after a ``clean-evals run``.
- The Celery task that runs evals scheduled by ``clean-evals beat``.
- The FastAPI app's read endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from clean_evals.models import (
    CaseResult,
    Dataset,
    ModelSummary,
    RunConfig,
    RunResult,
)
from clean_evals.storage.db import (
    CaseResultRow,
    CaseRow,
    DatasetRow,
    RunRow,
)


def upsert_dataset(session: Session, dataset: Dataset) -> DatasetRow:
    """Find or insert a ``DatasetRow`` matching ``(name, version)``.

    The row's cases are replaced wholesale on each call. Datasets are
    immutable once locked — callers should bump the version before editing.
    """
    row = session.execute(
        select(DatasetRow).where(
            DatasetRow.name == dataset.name, DatasetRow.version == dataset.version
        )
    ).scalar_one_or_none()
    if row is None:
        row = DatasetRow(
            name=dataset.name,
            version=dataset.version,
            description=dataset.description,
            scorer=dataset.scorer,
            scorer_config=dataset.scorer_config,
            request_shape=dataset.request_shape,
            system_prompt=dataset.system_prompt,
            shared_context=dataset.shared_context,
            user_template=dataset.user_template,
        )
        session.add(row)
        session.flush()  # need PK before adding child rows
    else:
        row.description = dataset.description
        row.scorer = dataset.scorer
        row.scorer_config = dataset.scorer_config
        row.request_shape = dataset.request_shape
        row.system_prompt = dataset.system_prompt
        row.shared_context = dataset.shared_context
        row.user_template = dataset.user_template

    # Replace cases.
    for old_row in list(row.cases):
        session.delete(old_row)
    session.flush()
    for case in dataset.cases:
        session.add(
            CaseRow(
                dataset_id=row.id,
                case_id_external=case.id,
                input_jsonb=case.input,
                expected_jsonb=case.expected,
                tags_jsonb=case.tags,
                locked=case.locked,
                metadata_jsonb=case.metadata,
            )
        )
    session.flush()
    # Refresh so callers see the new collection without stale ORM state.
    session.refresh(row, attribute_names=["cases"])
    return row


def persist_run(
    session: Session,
    *,
    result: RunResult,
    artifact_uri: str | None,
    triggered_by: str = "cli",
) -> RunRow:
    """Insert a completed run + per-case results."""
    ds_row = session.execute(
        select(DatasetRow).where(
            DatasetRow.name == result.dataset, DatasetRow.version == result.dataset_version
        )
    ).scalar_one_or_none()
    if ds_row is None:
        raise ValueError(
            f"Cannot persist run: dataset {result.dataset!r} {result.dataset_version!r} not found."
        )

    run_row = RunRow(
        id=result.run_id,
        dataset_id=ds_row.id,
        dataset_version=result.dataset_version,
        config_jsonb=result.config.model_dump(mode="json"),
        status="aborted" if any("aborted" in n for n in result.notes) else "done",
        started_at=result.started_at,
        finished_at=result.finished_at,
        summary_jsonb={m: s.model_dump(mode="json") for m, s in result.summary.items()},
        artifact_uri=artifact_uri,
        pricing_version=result.pricing_version,
        triggered_by=triggered_by,
    )
    session.add(run_row)
    for cr in result.cases:
        session.add(_case_result_to_row(result.run_id, cr))
    session.flush()
    return run_row


def hydrate_run(session: Session, run_id: str) -> RunResult | None:
    """Reconstruct a :class:`RunResult` from persisted rows."""
    row = session.get(RunRow, run_id)
    if row is None:
        return None
    ds_row = row.dataset
    config = RunConfig(**row.config_jsonb)
    cases: list[CaseResult] = []
    for cr in row.case_results:
        cases.append(_row_to_case_result(cr))
    summary = {
        model: ModelSummary(**payload) for model, payload in (row.summary_jsonb or {}).items()
    }
    return RunResult(
        run_id=row.id,
        dataset=ds_row.name,
        dataset_version=row.dataset_version,
        config=config,
        cases=cases,
        summary=summary,
        started_at=row.started_at or row.created_at,
        finished_at=row.finished_at or row.created_at,
        pricing_version=row.pricing_version,
        deterministic=config.temperature == 0.0,
        notes=[],
    )


def _case_result_to_row(run_id: str, cr: CaseResult) -> CaseResultRow:
    response_payload: dict[str, Any] | None = None
    if cr.response is not None:
        response_payload = {
            "content": cr.response.content,
            "parsed": cr.response.parsed,
        }
    return CaseResultRow(
        run_id=run_id,
        case_id=cr.case_id,
        model=cr.model,
        status=cr.status,
        score=cr.score.score if cr.score is not None else None,
        passed=cr.score.passed if cr.score is not None else None,
        response_jsonb=response_payload,
        latency_ms=cr.response.latency_ms if cr.response is not None else None,
        tokens_in=cr.response.tokens_in if cr.response is not None else None,
        tokens_out=cr.response.tokens_out if cr.response is not None else None,
        cost_usd=cr.response.cost_usd if cr.response is not None else None,
        error=cr.error,
        started_at=cr.started_at,
        finished_at=cr.finished_at,
    )


def _row_to_case_result(row: CaseResultRow) -> CaseResult:
    from clean_evals.models import ModelResponse, ScoreResult

    response: ModelResponse | None = None
    if row.response_jsonb is not None:
        response = ModelResponse(
            content=row.response_jsonb.get("content", ""),
            parsed=row.response_jsonb.get("parsed"),
            tokens_in=row.tokens_in or -1,
            tokens_out=row.tokens_out or -1,
            latency_ms=row.latency_ms or 0,
            cost_usd=row.cost_usd or 0.0,
            raw={},
        )
    score: ScoreResult | None = None
    if row.score is not None and row.passed is not None:
        score = ScoreResult(score=row.score, passed=row.passed, breakdown={}, notes=None)
    return CaseResult(
        case_id=row.case_id,
        model=row.model,
        status=row.status,  # type: ignore[arg-type]
        response=response,
        score=score,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def cumulative_cost_today(session: Session, today: datetime) -> float:
    """Sum ``cost_usd`` across case_results from ``today`` onward."""
    rows = session.execute(
        select(CaseResultRow.cost_usd).where(CaseResultRow.started_at >= today)
    ).all()
    return sum((r[0] or 0.0) for r in rows)


def spend_today(session: Session) -> float:
    """Total persisted spend since UTC midnight.

    Only persisted runs leave a cost trail — CLI runs without ``--persist``
    do not count. Callers feeding the daily cost limit should treat the
    figure as a floor, not the provider-billed truth.
    """
    now = datetime.now(UTC)
    return cumulative_cost_today(session, datetime(now.year, now.month, now.day, tzinfo=UTC))
