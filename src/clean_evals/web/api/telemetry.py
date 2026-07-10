"""Telemetry endpoints: ingest, inbox, promotion, spot checks, monitoring.

The batch ingest endpoint is the only authenticated surface in clean-evals.
It exists because telemetry is pushed by a production application, not
clicked by the local user — and it is dark by default: with
``CLEAN_EVALS_INGEST_TOKEN`` unset the route answers 404, so a default
install grows no new attack surface. The token protects this route only;
everything else remains unauthenticated and must stay unreachable from any
untrusted network (see the deployment guide).

Envelopes are stored raw unless ``CLEAN_EVALS_TELEMETRY_SCRUBBER`` is
configured — every ingest response repeats which scrubber ran (or ``null``).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clean_evals import telemetry_service
from clean_evals.storage.db import (
    CaseRow,
    TelemetryExchangeRow,
    TelemetryInteractionRow,
    session_factory,
)
from clean_evals.web.deps import get_session
from clean_evals.web.schemas import (
    AutolockStateOut,
    SpotCheckIn,
    TelemetryDeriveOut,
    TelemetryExchangeOut,
    TelemetryInboxOut,
    TelemetryIngestOut,
    TelemetryPromoteIn,
    TelemetryPromoteOut,
    TelemetryRejectionOut,
    TelemetryStatsOut,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def require_ingest_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token gate for the ingest route.

    404 (not 401) when no token is configured: the route does not exist on
    an instance that has not opted into ingest, and probing must not be able
    to tell the difference. Comparison is constant-time.
    """
    token = os.environ.get("CLEAN_EVALS_INGEST_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="Not Found")
    supplied = ""
    if authorization is not None and authorization.startswith("Bearer "):
        supplied = authorization[len("Bearer ") :].strip()
    if not supplied or not secrets.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="invalid ingest token")


def _scrubber_name() -> str | None:
    return os.environ.get("CLEAN_EVALS_TELEMETRY_SCRUBBER", "").strip() or None


async def _derive_in_background() -> None:
    try:
        await telemetry_service.derive_pending(session_factory())
    except Exception as exc:
        _log.warning("background telemetry derivation failed: %s", exc)


@router.post(
    "/interactions",
    response_model=TelemetryIngestOut,
    status_code=202,
    dependencies=[Depends(require_ingest_token)],
)
def ingest_interactions(
    payload: list[dict[str, Any]],
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
) -> TelemetryIngestOut:
    """Accept a batch of telemetry envelopes; derivation runs afterwards.

    Items are validated individually: a malformed envelope is rejected with
    its index and reason, the rest of the batch proceeds. Duplicate
    ``(source, interaction_id)`` pairs are skipped, so retrying a batch is
    idempotent.
    """
    if not payload:
        raise HTTPException(status_code=400, detail="empty batch")
    try:
        result = telemetry_service.ingest_items(session, payload)
    except ValueError as exc:  # misconfigured scrubber must fail loudly
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    background.add_task(_derive_in_background)
    return TelemetryIngestOut(
        accepted=result.accepted,
        duplicates=result.duplicates,
        rejected=[TelemetryRejectionOut(**r) for r in result.rejected],
        scrubber=_scrubber_name(),
    )


@router.post("/upload", response_model=TelemetryIngestOut, status_code=202)
async def upload_interactions(
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
    file: Annotated[UploadFile, File()],
) -> TelemetryIngestOut:
    """Manual ingest path: the same envelopes as JSONL, one per line."""
    raw = (await file.read()).decode("utf-8", errors="strict") if file else ""
    items: list[Any] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"line {lineno}: invalid JSON ({exc.msg})"
            ) from exc
    if not items:
        raise HTTPException(status_code=400, detail="no telemetry records found")
    try:
        result = telemetry_service.ingest_items(session, items)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    background.add_task(_derive_in_background)
    return TelemetryIngestOut(
        accepted=result.accepted,
        duplicates=result.duplicates,
        rejected=[TelemetryRejectionOut(**r) for r in result.rejected],
        scrubber=_scrubber_name(),
    )


@router.post("/derive", response_model=TelemetryDeriveOut)
async def derive_now() -> TelemetryDeriveOut:
    """Derive pending interactions inline and report what happened."""
    stats = await telemetry_service.derive_pending(session_factory())
    return TelemetryDeriveOut(
        interactions=stats.interactions,
        exchanges=stats.exchanges,
        auto_locked=stats.auto_locked,
        classifier_cost_usd=stats.classifier_cost_usd,
        skipped_budget=stats.skipped_budget,
        errors=stats.errors,
    )


@router.get("/inbox", response_model=TelemetryInboxOut)
def inbox(
    session: Annotated[Session, Depends(get_session)],
    dataset: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    status: Annotated[str, Query()] = "derived",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TelemetryInboxOut:
    """Derived exchanges awaiting review, newest first.

    ``status=promoted`` with open spot checks is how the spot-check queue
    is listed; the frontend requests ``spot_check=true`` via this endpoint's
    ``status`` filter plus client-side filtering on the returned rows.
    """
    conditions = [TelemetryExchangeRow.status == status]
    if dataset is not None:
        conditions.append(TelemetryInteractionRow.dataset_name == dataset)
    if source is not None:
        conditions.append(TelemetryInteractionRow.source == source)

    base = select(TelemetryExchangeRow, TelemetryInteractionRow).join(
        TelemetryInteractionRow,
        TelemetryInteractionRow.id == TelemetryExchangeRow.interaction_pk,
    )
    total = session.execute(
        select(func.count())
        .select_from(TelemetryExchangeRow)
        .join(
            TelemetryInteractionRow,
            TelemetryInteractionRow.id == TelemetryExchangeRow.interaction_pk,
        )
        .where(*conditions)
    ).scalar_one()
    rows = session.execute(
        base.where(*conditions).order_by(TelemetryExchangeRow.id.desc()).limit(limit).offset(offset)
    ).all()
    return TelemetryInboxOut(
        total=total,
        exchanges=[_exchange_out(ex, inter) for ex, inter in rows],
    )


@router.post("/exchanges/{exchange_id}/promote", response_model=TelemetryPromoteOut)
def promote(
    exchange_id: int,
    payload: TelemetryPromoteIn,
    session: Annotated[Session, Depends(get_session)],
) -> TelemetryPromoteOut:
    try:
        case_pk = telemetry_service.promote_exchange(
            session, exchange_id, lock=payload.lock, expected_override=payload.expected
        )
    except ValueError as exc:
        status = 409 if "already promoted" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    case = session.get(CaseRow, case_pk)
    assert case is not None  # promote_exchange just created it
    return TelemetryPromoteOut(case_id=case_pk, dataset_id=case.dataset_id)


@router.post("/exchanges/{exchange_id}/discard", status_code=204)
def discard(
    exchange_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> None:
    try:
        telemetry_service.discard_exchange(session, exchange_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/exchanges/{exchange_id}/spot-check", status_code=204)
def spot_check(
    exchange_id: int,
    payload: SpotCheckIn,
    session: Annotated[Session, Depends(get_session)],
) -> None:
    try:
        telemetry_service.resolve_spot_check(
            session, exchange_id, overturn=payload.resolution == "overturned"
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/spot-checks", response_model=TelemetryInboxOut)
def open_spot_checks(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TelemetryInboxOut:
    """Auto-locked exchanges awaiting their spot-check resolution."""
    conditions = [
        TelemetryExchangeRow.spot_check.is_(True),
        TelemetryExchangeRow.spot_check_resolved.is_(None),
    ]
    total = session.execute(
        select(func.count()).select_from(TelemetryExchangeRow).where(*conditions)
    ).scalar_one()
    rows = session.execute(
        select(TelemetryExchangeRow, TelemetryInteractionRow)
        .join(
            TelemetryInteractionRow,
            TelemetryInteractionRow.id == TelemetryExchangeRow.interaction_pk,
        )
        .where(*conditions)
        .order_by(TelemetryExchangeRow.id.desc())
        .limit(limit)
    ).all()
    return TelemetryInboxOut(
        total=total,
        exchanges=[_exchange_out(ex, inter) for ex, inter in rows],
    )


@router.get("/stats", response_model=TelemetryStatsOut)
def stats(
    session: Annotated[Session, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> TelemetryStatsOut:
    return TelemetryStatsOut(**telemetry_service.telemetry_stats(session, days=days))


@router.get("/autolock", response_model=AutolockStateOut)
def autolock(session: Annotated[Session, Depends(get_session)]) -> AutolockStateOut:
    return AutolockStateOut(**telemetry_service.autolock_state(session))


def _exchange_out(ex: TelemetryExchangeRow, inter: TelemetryInteractionRow) -> TelemetryExchangeOut:
    return TelemetryExchangeOut(
        id=ex.id,
        interaction_id=inter.interaction_id,
        source=inter.source,
        dataset=inter.dataset_name,
        kind=inter.kind,
        occurred_at=inter.occurred_at,
        outcome=inter.outcome,
        turn_index=ex.turn_index,
        context=list((ex.context_jsonb or {}).get("turns", [])),
        request_text=ex.request_text,
        request_input=ex.request_input_jsonb,
        response_text=ex.response_text,
        response_parsed=ex.response_parsed_jsonb,
        response_model=ex.response_model,
        alternatives=list((ex.alternatives_jsonb or {}).get("items", [])),
        regen_count=ex.regen_count,
        label=ex.label,
        verdict=ex.verdict,
        rating=ex.rating,
        feedback=ex.feedback,
        proposed_expected=ex.proposed_expected_jsonb,
        judge_score=ex.judge_score,
        status=ex.status,
        promoted_case_id=ex.promoted_case_id,
        auto_locked=ex.auto_locked,
        spot_check=ex.spot_check,
        spot_check_resolved=ex.spot_check_resolved,
    )
