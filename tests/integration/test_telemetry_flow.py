"""Telemetry end to end against the fake provider and a migrated database.

Ingest a production transcript -> derive exchanges (classifier pointed at
the fake local model) -> promote the accepted exchange into a chat-shaped
dataset -> run an eval that replays the conversation context. No API cost.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from clean_evals.eval_service import execute_run
from clean_evals.models import RunConfig
from clean_evals.web.app import app

pytestmark = pytest.mark.integration

MODEL = "local/fake-1"


def _transcript_envelope() -> dict[str, object]:
    return {
        "interaction_id": "conv-e2e-1",
        "occurred_at": datetime(2026, 7, 10, 12, 0, tzinfo=UTC).isoformat(),
        "source": "shop-prod",
        "dataset": "reply-sentiment",
        "model": MODEL,
        "kind": "transcript",
        "turns": [
            {"role": "user", "text": "How do people feel about this? 'I love this product'"},
            {"role": "assistant", "text": "positive"},
        ],
        "outcome": {"type": "accept"},
    }


def test_telemetry_ingest_promote_and_replay(
    migrated_sqlite: str,
    fake_openai_server: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_artifact_dir: object,
) -> None:
    # The classifier goes to the fake provider too — it returns no usable
    # labels, which must degrade gracefully (the accept outcome still rates
    # the final exchange; nothing is invented).
    monkeypatch.setenv("CLEAN_EVALS_TELEMETRY_CLASSIFIER_MODEL", MODEL)
    monkeypatch.setenv("CLEAN_EVALS_INGEST_TOKEN", "e2e-token")

    with TestClient(app) as client:
        # 1. Ingest through the token-gated endpoint.
        resp = client.post(
            "/api/v1/telemetry/interactions",
            json=[_transcript_envelope()],
            headers={"Authorization": "Bearer e2e-token"},
        )
        assert resp.status_code == 202, resp.text
        assert resp.json()["accepted"] == 1

        # 2. The background pass derived the exchange with its accept signal.
        inbox = client.get("/api/v1/telemetry/inbox").json()
        assert inbox["total"] == 1
        exchange = inbox["exchanges"][0]
        assert exchange["verdict"] == "positive"
        assert exchange["rating"] == 5
        assert exchange["kind"] == "transcript"

        # 3. Promote and lock; the dataset is created chat-shaped.
        promoted = client.post(
            f"/api/v1/telemetry/exchanges/{exchange['id']}/promote", json={"lock": True}
        )
        assert promoted.status_code == 200, promoted.text
        dataset_id = promoted.json()["dataset_id"]
        dataset = client.get(f"/api/v1/datasets/{dataset_id}").json()
        assert dataset["request_shape"] == "chat"

        # 4. Replaying the case sends the production request to the model.
        preview = client.get(f"/api/v1/datasets/{dataset_id}/preview-request").json()
        assert preview["user"].startswith("How do people feel")

    # 5. A real eval run replays the conversation against the fake provider.
    #    The llm_judge scorer skips without a key (score 0); what matters
    #    here is that the chat case executes, not how it scores.
    run_id = execute_run(
        dataset_id,
        RunConfig(models=[MODEL], max_cost_usd=1.0),
        triggered_by="api",
    )
    with TestClient(app) as client:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        assert run["status"] == "done"
        results = client.get(f"/api/v1/runs/{run_id}/cases").json()
        assert len(results) == 1
        assert results[0]["status"] == "ok"
        assert json.loads(json.dumps(results[0]["response"]))  # stored payload round-trips
