"""Telemetry endpoints: token gate, ingest, upload, inbox, promote, stats."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clean_evals.web.app import app

_TS = datetime(2026, 7, 10, 12, 0, tzinfo=UTC).isoformat()


def _structured_item(interaction_id: str = "web-1") -> dict[str, Any]:
    return {
        "interaction_id": interaction_id,
        "occurred_at": _TS,
        "source": "app-prod",
        "dataset": "triage",
        "model": "claude-sonnet-5",
        "kind": "structured",
        "request": {"input": {"text": "printer broken"}},
        "response": {"content": '{"queue": "hardware"}', "parsed": {"queue": "hardware"}},
        "events": [{"type": "accept"}],
    }


def test_ingest_is_dark_without_token(sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.post("/api/v1/telemetry/interactions", json=[_structured_item()])
        assert resp.status_code == 404


def test_ingest_rejects_bad_token(sqlite_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLEAN_EVALS_INGEST_TOKEN", "s3cret")
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/telemetry/interactions",
            json=[_structured_item()],
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401
        resp = client.post("/api/v1/telemetry/interactions", json=[_structured_item()])
        assert resp.status_code == 401


def test_ingest_accepts_batch_and_derives(sqlite_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLEAN_EVALS_INGEST_TOKEN", "s3cret")
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/telemetry/interactions",
            json=[_structured_item(), {"interaction_id": "junk"}],
            headers={"Authorization": "Bearer s3cret"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["accepted"] == 1
        assert body["rejected"][0]["index"] == 1
        assert body["scrubber"] is None  # stored raw, stated plainly

        # TestClient runs background tasks before returning: already derived.
        inbox = client.get("/api/v1/telemetry/inbox").json()
        assert inbox["total"] == 1
        ex = inbox["exchanges"][0]
        assert ex["verdict"] == "positive"
        assert ex["rating"] == 5
        assert ex["proposed_expected"] == {"queue": "hardware"}


def test_upload_jsonl_roundtrip(sqlite_engine) -> None:
    lines = "\n".join(json.dumps(_structured_item(f"up-{i}")) for i in range(2))
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/telemetry/upload",
            files={"file": ("telemetry.jsonl", lines, "application/jsonl")},
        )
        assert resp.status_code == 202
        assert resp.json()["accepted"] == 2


def test_upload_malformed_jsonl_400(sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/telemetry/upload",
            files={"file": ("telemetry.jsonl", "{not json", "application/jsonl")},
        )
        assert resp.status_code == 400
        assert "line 1" in resp.json()["detail"]


def test_promote_endpoint_locks_case(sqlite_engine) -> None:
    with TestClient(app) as client:
        client.post(
            "/api/v1/telemetry/upload",
            files={"file": ("t.jsonl", json.dumps(_structured_item("p-1")), "text/plain")},
        )
        exchange = client.get("/api/v1/telemetry/inbox").json()["exchanges"][0]
        resp = client.post(
            f"/api/v1/telemetry/exchanges/{exchange['id']}/promote", json={"lock": True}
        )
        assert resp.status_code == 200
        case_id = resp.json()["case_id"]
        dataset_id = resp.json()["dataset_id"]

        cases = client.get(f"/api/v1/datasets/{dataset_id}/cases").json()
        promoted = next(c for c in cases if c["id"] == case_id)
        assert promoted["locked"] is True
        assert promoted["expected"] == {"queue": "hardware"}

        # The inbox no longer lists it.
        assert client.get("/api/v1/telemetry/inbox").json()["total"] == 0


def test_discard_endpoint(sqlite_engine) -> None:
    with TestClient(app) as client:
        client.post(
            "/api/v1/telemetry/upload",
            files={"file": ("t.jsonl", json.dumps(_structured_item("d-1")), "text/plain")},
        )
        exchange = client.get("/api/v1/telemetry/inbox").json()["exchanges"][0]
        resp = client.post(f"/api/v1/telemetry/exchanges/{exchange['id']}/discard")
        assert resp.status_code == 204
        assert client.get("/api/v1/telemetry/inbox").json()["total"] == 0


def test_stats_and_autolock_endpoints(sqlite_engine) -> None:
    with TestClient(app) as client:
        client.post(
            "/api/v1/telemetry/upload",
            files={"file": ("t.jsonl", json.dumps(_structured_item("st-1")), "text/plain")},
        )
        stats = client.get("/api/v1/telemetry/stats").json()
        assert stats["days"] == 30
        assert stats["series"][0]["exchanges"] == 1
        assert stats["series"][0]["acceptance_rate"] == 1.0

        autolock = client.get("/api/v1/telemetry/autolock").json()
        assert autolock["enabled"] is False
        assert autolock["self_disabled"] is False

        spot = client.get("/api/v1/telemetry/spot-checks").json()
        assert spot["total"] == 0
