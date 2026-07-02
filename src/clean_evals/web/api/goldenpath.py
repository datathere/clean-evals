"""Golden-path endpoints — stages 1 through 4 of docs/docs/flow.md.

Everything here works on a bare ``pip install`` self-hosted instance: no
queue, no external services. Candidate generation runs as an in-process
background task on the API's event loop and is polled via the status
endpoint; calibration runs inline (bounded by the number of rated
outputs).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from clean_evals.calibration import calibrate
from clean_evals.candidates import GenerationJob, current_job, generate_candidates
from clean_evals.models import ModelParams
from clean_evals.prompting import assemble
from clean_evals.storage.db import (
    CandidateOutputRow,
    CaseRow,
    DatasetRow,
    JudgeConfigRow,
    RatingRow,
    RunRow,
    session_factory,
)
from clean_evals.suggestions import suggest_models
from clean_evals.web.api.datasets import dataset_out
from clean_evals.web.deps import get_session
from clean_evals.web.schemas import (
    CalibrateIn,
    CandidateOut,
    CaseOut,
    DatasetOut,
    DatasetSettingsIn,
    GenerateIn,
    GenerationStatusOut,
    GoldenPickIn,
    JudgeConfigOut,
    ModelPickOut,
    PromptSpecIn,
    RatingIn,
    RequestPreviewOut,
    SuggestionOut,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/datasets", tags=["golden-path"])


# ---------------------------------------------------------------------------
# Stage 1 — prompt spec + request preview
# ---------------------------------------------------------------------------


@router.patch("/{dataset_id}/prompt-spec", response_model=DatasetOut)
def set_prompt_spec(
    dataset_id: int,
    payload: PromptSpecIn,
    session: Annotated[Session, Depends(get_session)],
) -> DatasetOut:
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    row.request_shape = payload.request_shape
    row.system_prompt = payload.system_prompt
    row.shared_context = payload.shared_context
    row.user_template = payload.user_template
    session.flush()
    return dataset_out(row)


@router.patch("/{dataset_id}/settings", response_model=DatasetOut)
def edit_settings(
    dataset_id: int,
    payload: DatasetSettingsIn,
    session: Annotated[Session, Depends(get_session)],
) -> DatasetOut:
    """Edit the prompt spec and scorer configuration.

    Refused once runs reference the dataset: results scored under one
    configuration must stay comparable. Create a new version instead.
    """
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    if _dataset_has_runs(session, dataset_id):
        raise HTTPException(
            status_code=409,
            detail="runs reference this dataset; create a new version to edit settings",
        )
    if payload.scorer_config is not None:
        from clean_evals.registry import scorers

        try:
            scorers.get(row.scorer).from_config(payload.scorer_config)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid scorer config: {exc}") from exc
        row.scorer_config = payload.scorer_config
    if payload.system_prompt is not None:
        row.system_prompt = payload.system_prompt.strip() or None
    if payload.shared_context is not None:
        row.shared_context = payload.shared_context.strip() or None
    if payload.user_template is not None:
        row.user_template = payload.user_template.strip() or None
    session.flush()
    return dataset_out(row)


@router.get("/{dataset_id}/preview-request", response_model=RequestPreviewOut)
def preview_request(
    dataset_id: int,
    session: Annotated[Session, Depends(get_session)],
    case_id: int | None = Query(None, description="Case pk; defaults to the first case"),
) -> RequestPreviewOut:
    """The exact (system, user) pair the first case would send — stage 1 preview."""
    ds = session.get(DatasetRow, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    stmt = select(CaseRow).where(CaseRow.dataset_id == dataset_id).order_by(CaseRow.id)
    if case_id is not None:
        stmt = stmt.where(CaseRow.id == case_id)
    case = session.execute(stmt.limit(1)).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="dataset has no cases")
    try:
        request = assemble(
            request_shape=ds.request_shape,
            system_prompt=ds.system_prompt,
            shared_context=ds.shared_context,
            user_template=ds.user_template,
            case_input=dict(case.input_jsonb or {}),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=400, detail=f"user_template references a missing field: {exc}"
        ) from exc
    return RequestPreviewOut(
        case_id_external=case.case_id_external, system=request.system, user=request.user
    )


@router.post("/{dataset_id}/suggest-models", response_model=SuggestionOut)
async def suggest_models_endpoint(dataset_id: int) -> SuggestionOut:
    """Two cheap, two medium, two expensive models suited to this dataset."""
    try:
        suggestion = await suggest_models(session_factory(), dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuggestionOut(
        picks=[ModelPickOut(model=p.model, tier=p.tier, reason=p.reason) for p in suggestion.picks],
        picked_by=suggestion.picked_by,
    )


# ---------------------------------------------------------------------------
# Stage 2 — candidate generation
# ---------------------------------------------------------------------------


@router.post("/{dataset_id}/candidates", response_model=GenerationStatusOut, status_code=202)
def start_generation(
    dataset_id: int,
    payload: GenerateIn,
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
) -> GenerationStatusOut:
    ds = session.get(DatasetRow, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    if not ds.cases:
        raise HTTPException(status_code=400, detail="dataset has no cases")
    job = current_job(dataset_id)
    if job is not None and job.status == "running":
        return GenerationStatusOut(
            status=job.status,
            total=job.total,
            done=job.done,
            errors=job.errors,
            cost_usd=job.cost_usd,
        )

    new_job = GenerationJob(dataset_id=dataset_id, models=list(payload.models))

    model_params = {
        model: ModelParams(**params.model_dump()) for model, params in payload.model_params.items()
    }

    async def run() -> None:
        try:
            await generate_candidates(
                session_factory(),
                dataset_id,
                payload.models,
                temperature=payload.temperature,
                max_cost_usd=payload.max_cost_usd,
                model_params=model_params,
                job=new_job,
            )
        except Exception as exc:  # surfaced via the status endpoint
            _log.warning("candidate generation for dataset %s failed: %s", dataset_id, exc)
            if new_job.status == "running":
                new_job.status = "error"
                new_job.detail = str(exc)

    background.add_task(run)
    return GenerationStatusOut(status="running", total=len(ds.cases) * len(payload.models))


@router.get("/{dataset_id}/candidates/status", response_model=GenerationStatusOut)
def generation_status(
    dataset_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> GenerationStatusOut:
    count = len(
        session.execute(
            select(CandidateOutputRow.id)
            .join(CaseRow, CaseRow.id == CandidateOutputRow.case_id)
            .where(CaseRow.dataset_id == dataset_id)
        ).all()
    )
    job = current_job(dataset_id)
    if job is None:
        return GenerationStatusOut(status="idle", candidate_count=count)
    return GenerationStatusOut(
        status=job.status,
        total=job.total,
        done=job.done,
        errors=job.errors,
        cost_usd=job.cost_usd,
        detail=job.detail,
        candidate_count=count,
    )


@router.get("/{dataset_id}/candidates", response_model=list[CandidateOut])
def list_candidates(
    dataset_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> list[CandidateOut]:
    rows = session.execute(
        select(CandidateOutputRow, CaseRow)
        .join(CaseRow, CaseRow.id == CandidateOutputRow.case_id)
        .where(CaseRow.dataset_id == dataset_id)
        .order_by(CaseRow.id, CandidateOutputRow.model)
    ).all()
    return [
        CandidateOut(
            id=cand.id,
            case_id=case.id,
            case_id_external=case.case_id_external,
            model=cand.model,
            content=cand.content,
            parsed=cand.parsed_jsonb,
            status=cand.status,
            error=cand.error,
            latency_ms=cand.latency_ms,
            cost_usd=cand.cost_usd,
            rating=cand.rating.rating if cand.rating else None,
            feedback=cand.rating.feedback if cand.rating else None,
        )
        for cand, case in rows
    ]


# ---------------------------------------------------------------------------
# Stage 3 — review: rate candidates, pick the golden answer
# ---------------------------------------------------------------------------


@router.put("/{dataset_id}/candidates/{candidate_id}/rating", response_model=CandidateOut)
def rate_candidate(
    dataset_id: int,
    candidate_id: int,
    payload: RatingIn,
    session: Annotated[Session, Depends(get_session)],
) -> CandidateOut:
    cand = session.get(CandidateOutputRow, candidate_id)
    if cand is None or cand.case.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="candidate not found")
    if cand.rating is None:
        cand.rating = RatingRow(rating=payload.rating, feedback=payload.feedback)
    else:
        cand.rating.rating = payload.rating
        cand.rating.feedback = payload.feedback
    session.flush()
    return CandidateOut(
        id=cand.id,
        case_id=cand.case_id,
        case_id_external=cand.case.case_id_external,
        model=cand.model,
        content=cand.content,
        parsed=cand.parsed_jsonb,
        status=cand.status,
        error=cand.error,
        latency_ms=cand.latency_ms,
        cost_usd=cand.cost_usd,
        rating=cand.rating.rating,
        feedback=cand.rating.feedback,
    )


@router.post("/{dataset_id}/cases/{case_id}/golden", response_model=CaseOut)
def pick_golden(
    dataset_id: int,
    case_id: int,
    payload: GoldenPickIn,
    session: Annotated[Session, Depends(get_session)],
) -> CaseOut:
    """Lock in the golden answer — from a candidate output or hand-written."""
    case = session.get(CaseRow, case_id)
    if case is None or case.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="case not found")

    expected = payload.expected
    if expected is None and payload.candidate_id is not None:
        cand = session.get(CandidateOutputRow, payload.candidate_id)
        if cand is None or cand.case_id != case.id:
            raise HTTPException(status_code=404, detail="candidate not found for this case")
        if cand.parsed_jsonb is not None:
            expected = cand.parsed_jsonb
        else:
            ds = case.dataset
            field = (ds.scorer_config or {}).get("field")
            key = field if isinstance(field, str) and field else "text"
            expected = {key: cand.content}
    if expected is None:
        raise HTTPException(status_code=400, detail="provide candidate_id or expected")

    if case.locked:
        # Repeating the same pick is a no-op; a different pick conflicts.
        if case.expected_jsonb == expected:
            return CaseOut(
                id=case.id,
                case_id_external=case.case_id_external,
                input=case.input_jsonb,
                expected=case.expected_jsonb,
                tags=case.tags_jsonb or [],
                locked=case.locked,
                rev=case.rev,
            )
        raise HTTPException(
            status_code=409, detail="case is locked with a different answer; unlock first"
        )

    case.expected_jsonb = expected
    case.locked = payload.lock
    case.rev = case.rev + 1
    session.flush()
    return CaseOut(
        id=case.id,
        case_id_external=case.case_id_external,
        input=case.input_jsonb,
        expected=case.expected_jsonb,
        tags=case.tags_jsonb or [],
        locked=case.locked,
        rev=case.rev,
    )


def _dataset_has_runs(session: Session, dataset_id: int) -> bool:
    return (
        session.execute(select(RunRow.id).where(RunRow.dataset_id == dataset_id).limit(1)).first()
        is not None
    )


def _next_version(session: Session, name: str, current: str) -> str:
    """v1 -> v2, skipping versions already taken for this name."""
    taken = {
        row.version
        for row in session.execute(select(DatasetRow).where(DatasetRow.name == name)).scalars()
    }
    base = int(current[1:]) if current.startswith("v") and current[1:].isdigit() else len(taken)
    candidate = base + 1
    while f"v{candidate}" in taken:
        candidate += 1
    return f"v{candidate}"


@router.post("/{dataset_id}/cases/{case_id}/unlock", response_model=CaseOut)
def unlock_case(
    dataset_id: int,
    case_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> CaseOut:
    """Unlock a golden answer for editing, while no runs depend on it."""
    case = session.get(CaseRow, case_id)
    if case is None or case.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="case not found")
    if _dataset_has_runs(session, dataset_id):
        raise HTTPException(
            status_code=409,
            detail="runs reference this dataset; create a new version to edit",
        )
    case.locked = False
    case.rev = case.rev + 1
    session.flush()
    return CaseOut(
        id=case.id,
        case_id_external=case.case_id_external,
        input=case.input_jsonb,
        expected=case.expected_jsonb,
        tags=case.tags_jsonb or [],
        locked=case.locked,
        rev=case.rev,
    )


@router.post("/{dataset_id}/versions", response_model=DatasetOut, status_code=201)
def new_version(
    dataset_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> DatasetOut:
    """Clone the dataset as the next version, cases unlocked for editing.

    Golden answers and the prompt spec carry over. Existing runs keep
    pointing at the old version, so history stays comparable.
    """
    ds = session.get(DatasetRow, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    clone = DatasetRow(
        name=ds.name,
        version=_next_version(session, ds.name, ds.version),
        description=ds.description,
        scorer=ds.scorer,
        scorer_config=ds.scorer_config,
        request_shape=ds.request_shape,
        system_prompt=ds.system_prompt,
        shared_context=ds.shared_context,
        user_template=ds.user_template,
    )
    session.add(clone)
    session.flush()
    for case in ds.cases:
        session.add(
            CaseRow(
                dataset_id=clone.id,
                case_id_external=case.case_id_external,
                input_jsonb=case.input_jsonb,
                expected_jsonb=case.expected_jsonb,
                tags_jsonb=case.tags_jsonb,
                locked=False,
                metadata_jsonb=case.metadata_jsonb,
            )
        )
    session.flush()
    return dataset_out(clone)


# ---------------------------------------------------------------------------
# Stage 4 — judge calibration
# ---------------------------------------------------------------------------


@router.post("/{dataset_id}/judge/calibrate", response_model=JudgeConfigOut)
async def calibrate_judge(
    dataset_id: int,
    payload: CalibrateIn,
) -> JudgeConfigOut:
    try:
        config = await calibrate(session_factory(), dataset_id, judge_model=payload.judge_model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JudgeConfigOut(
        id=config.id,
        dataset_id=config.dataset_id,
        version=config.version,
        judge_model=config.judge_model,
        agreement=config.agreement_jsonb,
        created_at=config.created_at,
    )


@router.get("/{dataset_id}/judge", response_model=JudgeConfigOut | None)
def latest_judge_config(
    dataset_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> JudgeConfigOut | None:
    """The latest calibrated judge standard, or null when none exists."""
    row = session.execute(
        select(JudgeConfigRow)
        .where(JudgeConfigRow.dataset_id == dataset_id)
        .order_by(JudgeConfigRow.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return JudgeConfigOut(
        id=row.id,
        dataset_id=row.dataset_id,
        version=row.version,
        judge_model=row.judge_model,
        agreement=row.agreement_jsonb,
        created_at=row.created_at,
    )
