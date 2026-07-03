"""Run endpoints.

Plus the recommendations + cost-projection endpoints — they live here
because they're keyed off a run id.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from clean_evals import jobs
from clean_evals._internal.recommendations import all_three
from clean_evals.eval_service import run_inline, start_inline_job
from clean_evals.models import RunConfig
from clean_evals.storage.artifacts import build_artifact_store
from clean_evals.storage.db import CaseResultRow, CaseRow, RunRow
from clean_evals.storage.repo import hydrate_run
from clean_evals.web.deps import get_session
from clean_evals.web.schemas import (
    CaseResultOut,
    CostProjectionRequest,
    CostProjectionRow,
    InlineRunStatusOut,
    RecommendationOut,
    RunOut,
    RunSummaryRow,
    TriggerRunIn,
    TriggerRunOut,
)

router = APIRouter(prefix="/runs", tags=["runs"])


def _row_to_out(row: RunRow) -> RunOut:
    summary = {
        m: RunSummaryRow.model_validate(payload) for m, payload in (row.summary_jsonb or {}).items()
    }
    return RunOut(
        id=row.id,
        dataset=row.dataset.name,
        dataset_id=row.dataset_id,
        dataset_version=row.dataset_version,
        config=row.config_jsonb,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        summary=summary,
        artifact_uri=row.artifact_uri,
        pricing_version=row.pricing_version,
        triggered_by=row.triggered_by,
        created_at=row.created_at,
    )


@router.get("", response_model=list[RunOut])
def list_runs(
    session: Annotated[Session, Depends(get_session)],
    dataset_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[RunOut]:
    stmt = select(RunRow).order_by(RunRow.created_at.desc()).limit(limit).offset(offset)
    if dataset_id is not None:
        stmt = stmt.where(RunRow.dataset_id == dataset_id)
    rows = session.execute(stmt).scalars().all()
    return [_row_to_out(r) for r in rows]


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, session: Annotated[Session, Depends(get_session)]) -> RunOut:
    row = session.get(RunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _row_to_out(row)


@router.get("/{run_id}/cases", response_model=list[CaseResultOut])
def get_case_results(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[CaseResultOut]:
    run_row = session.get(RunRow, run_id)
    if run_row is None:
        raise HTTPException(status_code=404, detail="run not found")
    rows = (
        session.execute(select(CaseResultRow).where(CaseResultRow.run_id == run_id)).scalars().all()
    )
    # Join against the golden dataset so the UI can render expected-vs-got.
    golden = {
        c.case_id_external: c
        for c in session.execute(
            select(CaseRow).where(CaseRow.dataset_id == run_row.dataset_id)
        ).scalars()
    }
    out: list[CaseResultOut] = []
    for r in rows:
        case = golden.get(r.case_id)
        out.append(
            CaseResultOut(
                case_id=r.case_id,
                model=r.model,
                status=r.status,
                score=r.score,
                passed=r.passed,
                latency_ms=r.latency_ms,
                cost_usd=r.cost_usd,
                error=r.error,
                started_at=r.started_at,
                finished_at=r.finished_at,
                input=case.input_jsonb if case is not None else None,
                expected=case.expected_jsonb if case is not None else None,
                response=r.response_jsonb,
            )
        )
    return out


@router.get("/{run_id}/recommendations", response_model=list[RecommendationOut])
def recommendations(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    threshold: float = Query(0.80, ge=0.0, le=1.0),
) -> list[RecommendationOut]:
    result = hydrate_run(session, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run not found")
    recs = all_three(result, threshold=threshold)
    return [
        RecommendationOut(
            kind=rec.kind,  # type: ignore[arg-type]
            model=rec.model,
            rationale=rec.rationale,
            summary=RunSummaryRow.model_validate(rec.summary.model_dump()) if rec.summary else None,
        )
        for rec in recs.values()
    ]


@router.post("/{run_id}/cost-projection", response_model=list[CostProjectionRow])
def cost_projection(
    run_id: str,
    body: CostProjectionRequest,
    session: Annotated[Session, Depends(get_session)],
) -> list[CostProjectionRow]:
    if body.run_id != run_id:
        raise HTTPException(status_code=400, detail="run_id mismatch between URL and body")
    result = hydrate_run(session, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run not found")
    rows: list[CostProjectionRow] = []
    cases_per_run = max(1, len({c.case_id for c in result.cases}))
    for s in result.summary.values():
        per_call = s.total_cost_usd / cases_per_run if cases_per_run else 0.0
        rows.append(
            CostProjectionRow(
                model=s.model,
                score_mean=s.score_mean,
                qualifies=s.score_mean >= body.score_floor,
                projected_monthly_usd=per_call * body.calls_per_month,
            )
        )
    return rows


@router.post("", response_model=TriggerRunOut, status_code=202)
def trigger_run(
    body: TriggerRunIn,
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
) -> TriggerRunOut:
    """Start an eval run.

    ``mode="inline"`` (default) runs in-process — nothing beyond the web
    server is needed on a self-hosted install. ``mode="queue"`` enqueues
    via Celery for deployments that run workers.
    """
    try:
        config = RunConfig.model_validate(body.config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid config: {exc}") from exc

    if body.mode == "queue":
        from clean_evals.queue.tasks import run_eval

        async_result = run_eval.delay(
            dataset_id=body.dataset_id, config=body.config, triggered_by="web"
        )
        return TriggerRunOut(mode="queue", task_id=async_result.id)

    from clean_evals.storage.db import session_factory

    existing = jobs.mark_lost_if_stale(
        session_factory(),
        jobs.latest(session, kind=jobs.INLINE_RUN, dataset_id=body.dataset_id),
    )
    if existing is not None and existing.status == "running":
        raise HTTPException(status_code=409, detail="a run is already in progress")
    job_id = start_inline_job(body.dataset_id)
    background.add_task(run_inline, body.dataset_id, config, job_id)
    return TriggerRunOut(mode="inline")


@router.get("/inline-status/{dataset_id}", response_model=InlineRunStatusOut)
def inline_run_status(
    dataset_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> InlineRunStatusOut:
    from clean_evals.storage.db import session_factory

    row = jobs.mark_lost_if_stale(
        session_factory(), jobs.latest(session, kind=jobs.INLINE_RUN, dataset_id=dataset_id)
    )
    if row is None:
        return InlineRunStatusOut(status="idle")
    return InlineRunStatusOut(status=row.status, run_id=row.run_id, detail=row.detail)


@router.get("/{run_id}/artifacts/{name}")
def fetch_artifact(
    run_id: str,
    name: str,
    session: Annotated[Session, Depends(get_session)],
) -> StreamingResponse:
    row = session.get(RunRow, run_id)
    if row is None or not row.artifact_uri:
        raise HTTPException(status_code=404, detail="artifact not found")
    store = build_artifact_store()
    try:
        stream = store.open_read(row.artifact_uri, name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    media = "text/markdown" if name.endswith(".md") else "application/octet-stream"
    return StreamingResponse(stream, media_type=media)
