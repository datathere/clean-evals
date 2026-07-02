"""Dataset Builder upload endpoint.

Accepts CSV, JSON, JSONL, or YAML and creates an in-progress dataset row
with one ``CaseRow`` per input. The Builder UI then runs candidate models
against each case and lets users pick / edit / lock the expected output.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from clean_evals.storage.db import CaseRow, DatasetRow
from clean_evals.web.deps import get_session

router = APIRouter(prefix="/builder", tags=["builder"])


@router.post("/upload")
async def upload_inputs(
    name: Annotated[str, Form()],
    version: Annotated[str, Form()],
    scorer: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    session: Annotated[Session, Depends(get_session)],
    description: Annotated[str | None, Form()] = None,
    request_shape: Annotated[str, Form()] = "raw",
    system_prompt: Annotated[str | None, Form()] = None,
    shared_context: Annotated[str | None, Form()] = None,
    user_template: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    if request_shape not in {"raw", "templated"}:
        raise HTTPException(status_code=400, detail="request_shape must be raw or templated")
    raw = (await file.read()).decode("utf-8", errors="replace")
    fname = (file.filename or "upload").lower()

    rows: list[dict[str, Any]]
    if fname.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(raw))
        rows = [dict(r) for r in reader]
    elif fname.endswith(".jsonl"):
        rows = []
        for lineno, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400, detail=f"line {lineno}: invalid JSON ({exc})"
                ) from exc
    elif fname.endswith(".json"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON ({exc})") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="JSON must be an array of objects")
        rows = parsed
    elif fname.endswith((".yml", ".yaml")):
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=400, detail=f"invalid YAML ({exc})") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="YAML must be a list at the top level")
        rows = parsed
    else:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported extension on {fname!r}; use csv/json/jsonl/yaml",
        )

    if not rows:
        raise HTTPException(status_code=400, detail="no input rows found")

    ds = DatasetRow(
        name=name,
        version=version,
        description=description,
        scorer=scorer,
        scorer_config={},
        request_shape=request_shape,
        system_prompt=system_prompt,
        shared_context=shared_context,
        user_template=user_template,
    )
    session.add(ds)
    session.flush()

    for i, row in enumerate(rows):
        external = str(row.get("id") or f"case_{i + 1:04d}")
        session.add(
            CaseRow(
                dataset_id=ds.id,
                case_id_external=external,
                input_jsonb=row,
                expected_jsonb=None,
                tags_jsonb=[],
                locked=False,
                metadata_jsonb={},
            )
        )

    session.flush()
    return {"dataset_id": ds.id, "case_count": len(rows)}
