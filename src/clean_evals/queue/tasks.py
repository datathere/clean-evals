"""Celery task definitions.

A single canonical task — ``run_eval`` — runs a stored ``Dataset`` against a
``RunConfig``. Schedule rows in the DB enqueue this task via Celery Beat.
The body lives in :mod:`clean_evals.eval_service`, shared with the web
API's inline (no-queue) mode; this wrapper only adds the Redis event sink
so the UI sees live progress from workers.
"""

from __future__ import annotations

import logging
from typing import Any

from clean_evals.eval_service import execute_run
from clean_evals.models import RunConfig
from clean_evals.queue.app import app
from clean_evals.queue.events import RedisEventSink

_log = logging.getLogger(__name__)


@app.task(name="clean_evals.run_eval", bind=True)  # type: ignore[untyped-decorator]  # celery ships no stubs
def run_eval(
    self: Any,  # noqa: ARG001 — Celery wants self
    *,
    dataset_id: int,
    config: dict[str, Any],
    triggered_by: str = "schedule",
) -> dict[str, Any]:
    """Run an eval scheduled or invoked from the web UI.

    Returns a small JSON-friendly payload (just the run id) — the full
    result is on disk in the artifact store and in the DB.
    """
    run_id = execute_run(
        dataset_id,
        RunConfig.model_validate(config),
        triggered_by=triggered_by,
        event_sink=RedisEventSink(),
    )
    return {"run_id": run_id}
