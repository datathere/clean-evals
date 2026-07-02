"""Redis pub/sub plumbing for live run progress.

The runner emits :class:`~clean_evals._internal.events.RunEvent` messages.
``RedisEventSink`` publishes them as JSON to a channel; the FastAPI SSE
endpoint subscribes to the same channel and forwards each message to the
client.

We intentionally use a bare pub/sub channel rather than Redis Streams: SSE
is at-most-once and history is not part of the contract. The frontend
fetches the persisted ``RunResult`` once the run finishes.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis

from clean_evals._internal.events import RunEvent

_log = logging.getLogger(__name__)


def channel_name() -> str:
    """Return the configured pub/sub channel name."""
    return os.environ.get("CLEAN_EVALS_EVENT_CHANNEL", "clean_evals.events")


def redis_url() -> str:
    return os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")


class RedisEventSink:
    """Synchronous publisher used by the Celery worker."""

    def __init__(self, *, channel: str | None = None, url: str | None = None) -> None:
        self._channel = channel or channel_name()
        self._client: redis.Redis = redis.Redis.from_url(url or redis_url())

    def __call__(self, event: RunEvent) -> None:
        try:
            payload = event.model_dump_json()
            self._client.publish(self._channel, payload)
        except redis.RedisError as exc:  # pragma: no cover — log path
            _log.warning("Redis publish failed: %s", exc)


@asynccontextmanager
async def subscribe() -> AsyncIterator[AsyncIterator[RunEvent]]:
    """Async generator yielding :class:`RunEvent` objects from the pub/sub channel.

    Used by the FastAPI SSE endpoint:

    .. code-block:: python

        async with subscribe() as stream:
            async for event in stream:
                yield {"data": event.model_dump_json()}
    """
    import redis.asyncio as aioredis

    client: aioredis.Redis = aioredis.from_url(redis_url())  # type: ignore[no-untyped-call]
    pubsub = client.pubsub()
    await pubsub.subscribe(channel_name())

    async def gen() -> AsyncIterator[RunEvent]:
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    yield RunEvent.model_validate_json(data)
                except (ValueError, json.JSONDecodeError) as exc:
                    _log.debug("dropping malformed pub/sub payload: %s", exc)
                    continue
        finally:
            pass

    try:
        yield gen()
    finally:
        await pubsub.unsubscribe(channel_name())
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        await client.aclose()
