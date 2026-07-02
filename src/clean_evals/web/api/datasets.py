"""Datasets + cases endpoints.

Bulk read endpoints are paginated. Mutation endpoints around cases enforce
optimistic concurrency: the client passes the case's last-known ``rev``;
on conflict the server returns ``409`` and the client re-fetches.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from clean_evals.storage.db import CaseRow, DatasetRow
from clean_evals.web.deps import get_session
from clean_evals.web.schemas import CaseEditIn, CaseOut, DatasetOut

router = APIRouter(prefix="/datasets", tags=["datasets"])


def dataset_out(row: DatasetRow) -> DatasetOut:
    return DatasetOut(
        id=row.id,
        name=row.name,
        version=row.version,
        description=row.description,
        scorer=row.scorer,
        case_count=len(row.cases),
        locked_count=sum(1 for c in row.cases if c.locked),
        has_runs=len(row.runs) > 0,
        scorer_config=row.scorer_config or {},
        request_shape=row.request_shape,  # type: ignore[arg-type]
        system_prompt=row.system_prompt,
        shared_context=row.shared_context,
        user_template=row.user_template,
        locked_at=row.locked_at,
        created_at=row.created_at,
    )


@router.get("", response_model=list[DatasetOut])
def list_datasets(
    session: Annotated[Session, Depends(get_session)],
    name: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[DatasetOut]:
    stmt = select(DatasetRow).order_by(DatasetRow.created_at.desc()).limit(limit).offset(offset)
    if name:
        stmt = stmt.where(DatasetRow.name == name)
    rows = session.execute(stmt).scalars().all()
    return [dataset_out(r) for r in rows]


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> DatasetOut:
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return dataset_out(row)


@router.get("/{dataset_id}/cases", response_model=list[CaseOut])
def list_cases(
    dataset_id: int,
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[CaseOut]:
    stmt = (
        select(CaseRow)
        .where(CaseRow.dataset_id == dataset_id)
        .order_by(CaseRow.id)
        .limit(limit)
        .offset(offset)
    )
    rows = session.execute(stmt).scalars().all()
    return [
        CaseOut(
            id=r.id,
            case_id_external=r.case_id_external,
            input=r.input_jsonb,
            expected=r.expected_jsonb,
            tags=r.tags_jsonb or [],
            locked=r.locked,
            rev=r.rev,
        )
        for r in rows
    ]


@router.patch("/{dataset_id}/cases/{case_id}", response_model=CaseOut)
def edit_case(
    dataset_id: int,
    case_id: int,
    payload: CaseEditIn,
    session: Annotated[Session, Depends(get_session)],
) -> CaseOut:
    row = session.get(CaseRow, case_id)
    if row is None or row.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="case not found")
    if row.locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="case is locked; bump the dataset version to edit",
        )
    if row.rev != payload.rev:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stale rev", "current_rev": row.rev},
        )
    row.expected_jsonb = payload.expected
    row.rev = row.rev + 1
    session.flush()
    return CaseOut(
        id=row.id,
        case_id_external=row.case_id_external,
        input=row.input_jsonb,
        expected=row.expected_jsonb,
        tags=row.tags_jsonb or [],
        locked=row.locked,
        rev=row.rev,
    )


@router.post("/{dataset_id}/cases/{case_id}/lock", response_model=CaseOut)
def lock_case(
    dataset_id: int,
    case_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> CaseOut:
    row = session.get(CaseRow, case_id)
    if row is None or row.dataset_id != dataset_id:
        raise HTTPException(status_code=404, detail="case not found")
    if row.expected_jsonb is None:
        raise HTTPException(status_code=400, detail="case has no expected output to lock in")
    row.locked = True
    row.rev = row.rev + 1
    session.flush()
    return CaseOut(
        id=row.id,
        case_id_external=row.case_id_external,
        input=row.input_jsonb,
        expected=row.expected_jsonb,
        tags=row.tags_jsonb or [],
        locked=row.locked,
        rev=row.rev,
    )
