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
import time
from pathlib import Path

from sqlalchemy import select

from clean_evals import jobs
from clean_evals._internal.events import EventSink, RunEvent
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
#
# State lives in the ``jobs`` table (kind="inline_run") so it survives
# server restarts and is shared across worker processes. The runner's
# event sink doubles as the heartbeat: each finished case refreshes the
# row's ``updated_at`` (throttled), so a long run never reads as lost.

_HEARTBEAT_EVERY_S = 5.0


def start_inline_job(dataset_id: int) -> int:
    """Insert the ``running`` job row; returns the job id."""
    return jobs.create(session_factory(), kind=jobs.INLINE_RUN, dataset_id=dataset_id)


def run_inline(
    dataset_id: int,
    config: RunConfig,
    job_id: int,
    *,
    event_sink: EventSink | None = None,
) -> None:
    """Blocking body for the web API's background thread."""
    factory = session_factory()
    last_beat = time.monotonic()

    def sink(event: RunEvent) -> None:
        nonlocal last_beat
        if event_sink is not None:
            event_sink(event)
        now = time.monotonic()
        if now - last_beat >= _HEARTBEAT_EVERY_S:
            last_beat = now
            jobs.update(factory, job_id)

    try:
        run_id = execute_run(dataset_id, config, triggered_by="web", event_sink=sink)
        jobs.update(factory, job_id, status="done", run_id=run_id)
    except Exception as exc:
        _log.warning("inline run for dataset %s failed: %s", dataset_id, exc)
        jobs.update(factory, job_id, status="error", detail=str(exc))
