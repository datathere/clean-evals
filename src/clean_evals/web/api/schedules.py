"""Schedule CRUD."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from clean_evals.storage.db import ScheduleRow
from clean_evals.web.deps import get_session
from clean_evals.web.schemas import ScheduleIn, ScheduleOut

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleOut])
def list_schedules(session: Annotated[Session, Depends(get_session)]) -> list[ScheduleOut]:
    rows = session.execute(select(ScheduleRow).order_by(ScheduleRow.id)).scalars().all()
    return [
        ScheduleOut(
            id=r.id,
            dataset_id=r.dataset_id,
            cron=r.cron,
            enabled=r.enabled,
            config=r.config_jsonb,
            last_run_at=r.last_run_at,
            next_run_at=r.next_run_at,
        )
        for r in rows
    ]


@router.post("", response_model=ScheduleOut, status_code=201)
def create_schedule(
    body: ScheduleIn,
    session: Annotated[Session, Depends(get_session)],
) -> ScheduleOut:
    row = ScheduleRow(
        dataset_id=body.dataset_id,
        cron=body.cron,
        enabled=body.enabled,
        config_jsonb=body.config,
    )
    session.add(row)
    session.flush()
    return ScheduleOut(
        id=row.id,
        dataset_id=row.dataset_id,
        cron=row.cron,
        enabled=row.enabled,
        config=row.config_jsonb,
        last_run_at=row.last_run_at,
        next_run_at=row.next_run_at,
    )


@router.put("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: int,
    body: ScheduleIn,
    session: Annotated[Session, Depends(get_session)],
) -> ScheduleOut:
    row = session.get(ScheduleRow, schedule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    row.dataset_id = body.dataset_id
    row.cron = body.cron
    row.enabled = body.enabled
    row.config_jsonb = body.config
    session.flush()
    return ScheduleOut(
        id=row.id,
        dataset_id=row.dataset_id,
        cron=row.cron,
        enabled=row.enabled,
        config=row.config_jsonb,
        last_run_at=row.last_run_at,
        next_run_at=row.next_run_at,
    )


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> None:
    row = session.get(ScheduleRow, schedule_id)
    if row is None:
        return
    session.delete(row)
