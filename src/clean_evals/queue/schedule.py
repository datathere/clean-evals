"""DB-backed Celery Beat schedule loader.

Called by ``clean-evals beat``. Reads enabled rows from the ``schedules``
table and translates each cron string into a Celery Beat entry. Refreshed
on a short interval so adding a row in the UI takes effect within a
minute without restarting Beat.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from celery.schedules import crontab
from sqlalchemy import select

from clean_evals.queue.app import app
from clean_evals.storage.db import ScheduleRow, session_factory

_log = logging.getLogger(__name__)


def _parse_cron(expr: str) -> crontab | timedelta:
    """Accept either a 5-field cron expression or ``every 1m`` shorthand."""
    expr = expr.strip()
    if expr.startswith("every "):
        units = expr.split()[1]
        if units.endswith("s"):
            return timedelta(seconds=int(units[:-1]))
        if units.endswith("m"):
            return timedelta(minutes=int(units[:-1]))
        if units.endswith("h"):
            return timedelta(hours=int(units[:-1]))
        raise ValueError(f"unrecognised 'every' unit in {expr!r}")
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {len(fields)}: {expr!r}")
    minute, hour, day_of_month, month_of_year, day_of_week = fields
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def load_schedule() -> dict[str, dict[str, Any]]:
    """Return a Celery Beat schedule dict assembled from the DB."""
    factory = session_factory()
    out: dict[str, dict[str, Any]] = {}
    with factory() as session:
        rows = (
            session.execute(select(ScheduleRow).where(ScheduleRow.enabled.is_(True)))
            .scalars()
            .all()
        )
        for row in rows:
            try:
                schedule = _parse_cron(row.cron)
            except Exception as exc:
                _log.warning("bad cron in schedule id=%s (%r): %s", row.id, row.cron, exc)
                continue
            out[f"schedule-{row.id}"] = {
                "task": "clean_evals.run_eval",
                "schedule": schedule,
                "kwargs": {
                    "dataset_id": row.dataset_id,
                    "config": row.config_jsonb,
                    "triggered_by": "schedule",
                },
            }
    return out


def install_schedule() -> None:
    """Hook into Celery Beat: install the schedule on the live app."""
    app.conf.beat_schedule = load_schedule()
    # Re-read every 60 seconds so UI changes apply without a restart.
    app.conf.beat_max_loop_interval = 60
