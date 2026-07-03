"""Celery worker round-trip and SSE delivery over Redis.

Skipped unless a Redis broker is reachable. CI provides one; locally,
export CELERY_BROKER_URL to run these.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.integration

BROKER = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")


def _redis_available() -> bool:
    try:
        import redis

        redis.Redis.from_url(BROKER).ping()
        return True
    except Exception:
        return False


redis_required = pytest.mark.skipif(not _redis_available(), reason="no Redis broker reachable")

MODEL = "local/fake-1"


def _seed_dataset() -> int:
    """One case with a locked golden answer matching the fake model."""
    from clean_evals.storage.db import CaseRow, DatasetRow, session_factory

    with session_factory()() as session:
        ds = DatasetRow(name="q", version="v1", scorer="exact_match", scorer_config={})
        session.add(ds)
        session.flush()
        session.add(
            CaseRow(
                dataset_id=ds.id,
                case_id_external="c1",
                input_jsonb={"text": "I love it"},
                expected_jsonb={"text": "positive"},
                locked=True,
            )
        )
        session.commit()
        return ds.id


@redis_required
def test_celery_worker_round_trip(
    migrated_sqlite: str, fake_openai_server: str, tmp_artifact_dir
) -> None:
    from celery.contrib.testing.worker import start_worker

    from clean_evals.queue.app import app as celery_app
    from clean_evals.queue.tasks import run_eval
    from clean_evals.storage.db import session_factory
    from clean_evals.storage.repo import hydrate_run

    dataset_id = _seed_dataset()
    celery_app.conf.update(broker_url=BROKER, result_backend=BROKER)

    with start_worker(celery_app, perform_ping_check=False, shutdown_timeout=30):
        result = run_eval.delay(
            dataset_id=dataset_id,
            config={"models": [MODEL], "max_cost_usd": 1.0, "temperature": 0.0},
            triggered_by="test",
        )
        payload = result.get(timeout=30)

    run_id = payload["run_id"]
    with session_factory()() as session:
        run = hydrate_run(session, run_id)
    assert run is not None
    assert run.summary[MODEL].cases_passed == 1


@redis_required
@pytest.mark.asyncio
async def test_sse_delivers_run_events() -> None:
    """Events published by the sink reach a subscriber over Redis pub/sub."""
    from clean_evals._internal.events import RunEvent, now
    from clean_evals.queue.events import RedisEventSink, subscribe

    received: list[RunEvent] = []

    async with subscribe() as stream:
        # Publish from a thread once the subscription is attached; the sink
        # is synchronous.
        def publish() -> None:
            sink = RedisEventSink()
            sink(RunEvent(type="run.started", run_id="r_sse", at=now(), payload={}))
            sink(RunEvent(type="run.finished", run_id="r_sse", at=now(), payload={}))

        await asyncio.sleep(0.3)
        await asyncio.get_running_loop().run_in_executor(None, publish)

        async def collect() -> None:
            async for event in stream:
                if event.run_id == "r_sse":
                    received.append(event)
                    if len(received) >= 2:
                        return

        await asyncio.wait_for(collect(), timeout=10)

    types = {e.type for e in received}
    assert types == {"run.started", "run.finished"}
