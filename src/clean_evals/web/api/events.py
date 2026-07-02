"""SSE endpoint streaming live run progress.

Subscribes to the Redis pub/sub channel and forwards each ``RunEvent`` to
the client as a Server-Sent Event.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from clean_evals.queue.events import subscribe

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def stream_events(run_id: str | None = None) -> EventSourceResponse:
    """Stream live run progress.

    Pass ``run_id`` to filter to a single run; otherwise every event flows
    through. Events are JSON, encoded as the ``data:`` field.
    """

    async def generator() -> AsyncIterator[dict[str, str]]:
        async with subscribe() as stream:
            async for event in stream:
                if run_id is not None and event.run_id != run_id:
                    continue
                yield {"event": event.type, "data": event.model_dump_json()}

    return EventSourceResponse(generator())
