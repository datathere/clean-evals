"""Execute a stored dataset's eval run and persist everything.

Single implementation shared by three callers:

- the Celery task (``clean_evals.queue.tasks``) for scheduled runs,
- the web API's inline mode (background thread — no queue required on a
  self-hosted install),
- tests, which inject stub adapters.
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from clean_evals._internal.events import EventSink
from clean_evals.models import Case, Dataset, RunConfig
from clean_evals.protocols import ModelAdapter
from clean_evals.registry import reporters
from clean_evals.runner import Runner
from clean_evals.storage.artifacts import build_artifact_store
from clean_evals.storage.db import DatasetRow, session_factory
from clean_evals.storage.repo import persist_run, spend_today

_log = logging.getLogger(__name__)


def execute_run(
    dataset_id: int,
    config: RunConfig,
    *,
    triggered_by: str,
    event_sink: EventSink | None = None,
    adapters: dict[str, ModelAdapter] | None = None,
) -> str:
    """Run the eval synchronously and persist run + artifacts. Returns run id.

    Raises:
        ValueError: When the dataset row does not exist.
    """
    factory = session_factory()
    with factory() as session:
        ds_row: DatasetRow | None = session.execute(
            select(DatasetRow).where(DatasetRow.id == dataset_id)
        ).scalar_one_or_none()
        if ds_row is None:
            raise ValueError(f"Dataset row id={dataset_id} not found")

        cases = [
            Case(
                id=c.case_id_external,
                input=c.input_jsonb or {},
                expected=c.expected_jsonb,
                tags=c.tags_jsonb or [],
                metadata=c.metadata_jsonb or {},
                locked=c.locked,
            )
            for c in ds_row.cases
        ]
        dataset = Dataset(
            name=ds_row.name,
            version=ds_row.version,
            description=ds_row.description,
            cases=cases,
            scorer=ds_row.scorer,
            scorer_config=ds_row.scorer_config or {},
            request_shape=ds_row.request_shape,  # type: ignore[arg-type]
            system_prompt=ds_row.system_prompt,
            shared_context=ds_row.shared_context,
            user_template=ds_row.user_template,
        )
        today_spend = spend_today(session)

    runner = Runner(
        adapters=adapters,
        event_sink=event_sink,
        daily_cost_so_far_usd=today_spend,
    )
    result = runner.run_sync(dataset, config)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for name in ("markdown", "jsonl", "junit"):
            try:
                reporters.get(name)().write(result, out)
            except Exception as exc:
                _log.warning("Reporter %s failed: %s", name, exc)
        (out / "summary.json").write_text(
            json.dumps(
                {m: s.model_dump(mode="json") for m, s in result.summary.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        artifact_uri = build_artifact_store().write_dir(result.run_id, out)

    with factory() as session:
        persist_run(session, result=result, artifact_uri=artifact_uri, triggered_by=triggered_by)
        session.commit()

    return result.run_id


# ---------------------------------------------------------------------------
# Inline-run tracking (web API's no-queue mode)
# ---------------------------------------------------------------------------


@dataclass
class InlineRunJob:
    status: str = "running"  # running|done|error
    run_id: str | None = None
    detail: str | None = None


_inline_jobs: dict[int, InlineRunJob] = {}
_inline_lock = threading.Lock()


def inline_job(dataset_id: int) -> InlineRunJob | None:
    with _inline_lock:
        return _inline_jobs.get(dataset_id)


def start_inline_job(dataset_id: int) -> InlineRunJob:
    job = InlineRunJob()
    with _inline_lock:
        _inline_jobs[dataset_id] = job
    return job


def run_inline(dataset_id: int, config: RunConfig, job: InlineRunJob) -> None:
    """Blocking body for the web API's background thread."""
    try:
        job.run_id = execute_run(dataset_id, config, triggered_by="web")
        job.status = "done"
    except Exception as exc:
        _log.warning("inline run for dataset %s failed: %s", dataset_id, exc)
        job.status = "error"
        job.detail = str(exc)
