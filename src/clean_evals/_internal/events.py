"""Run-progress event channel.

Emitted by the runner; consumed by the FastAPI SSE endpoint via Redis
pub/sub so the Decision UI can show live progress without polling.

Design:

- ``RunEvent`` is the single shape on the wire. ``type`` discriminates.
- The runner writes events through a ``EventSink`` callable; the default
  is a no-op so headless CLI runs don't pull in Redis.
- The Celery task wraps the runner with a Redis-backed sink that publishes
  to ``CLEAN_EVALS_EVENT_CHANNEL``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class RunEvent(BaseModel):
    """A single progress event for an in-flight run."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "run.started",
        "run.case_started",
        "run.case_finished",
        "run.cost_warning",
        "run.finished",
    ]
    run_id: str
    at: datetime
    payload: dict[str, Any] = {}


def now() -> datetime:
    """Single source of truth for event timestamps. UTC, microsecond-precision."""
    return datetime.now(UTC)


EventSink = Callable[[RunEvent], None]
"""Pluggable receiver for ``RunEvent`` messages."""


def noop_sink(event: RunEvent) -> None:
    """Default sink: throw events away. Used by headless CLI runs."""
