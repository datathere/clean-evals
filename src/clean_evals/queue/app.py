"""Celery app factory.

Single shared instance. Broker and result backend come from
``CELERY_BROKER_URL`` / ``CELERY_RESULT_BACKEND`` (Redis by default).

We register the DB-backed Beat schedule lazily so that workers (which don't
need it) don't pay the import cost of the schedules table.
"""

from __future__ import annotations

import os

from celery import Celery


def _build_app() -> Celery:
    broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    backend = os.environ.get("CELERY_RESULT_BACKEND", broker)

    application = Celery(
        "clean_evals",
        broker=broker,
        backend=backend,
        include=["clean_evals.queue.tasks"],
    )
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
    )
    return application


app = _build_app()
