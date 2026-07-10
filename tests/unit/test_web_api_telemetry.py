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
        # Non-ASCII bearer values must 401, not crash compare_digest (500).
        # (Sent as latin-1 bytes — the wire format of HTTP headers.)
        resp = client.post(
            "/api/v1/telemetry/interactions",
            json=[_structured_item()],
            headers={"Authorization": "Bearer sécret".encode("latin-1")},
        )
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


def test_upload_non_utf8_400(sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/telemetry/upload",
            files={"file": ("telemetry.jsonl", b"\xff\xfe{bad}", "application/jsonl")},
        )
        assert resp.status_code == 400
        assert "UTF-8" in resp.json()["detail"]


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


def _transcript_item(interaction_id: str = "web-t-1") -> dict[str, Any]:
    return {
        "interaction_id": interaction_id,
        "occurred_at": _TS,
        "source": "app-prod",
        "dataset": "support-chat",
        "model": "claude-sonnet-5",
        "kind": "transcript",
        "turns": [
            {"role": "user", "text": "summarize this"},
            {"role": "assistant", "text": "Long summary."},
            {"role": "user", "text": "shorter please"},
            {"role": "assistant", "text": "Short summary."},
        ],
        "outcome": {"type": "accept"},
    }


def test_preview_shows_replayed_history_for_chat_cases(sqlite_engine) -> None:
    with TestClient(app) as client:
        client.post(
            "/api/v1/telemetry/upload",
            files={"file": ("t.jsonl", json.dumps(_transcript_item()), "text/plain")},
        )
        # The final (accepted) exchange carries two turns of context.
        exchanges = client.get("/api/v1/telemetry/inbox").json()["exchanges"]
        final = next(e for e in exchanges if e["verdict"] == "positive")
        dataset_id = client.post(
            f"/api/v1/telemetry/exchanges/{final['id']}/promote", json={"lock": True}
        ).json()["dataset_id"]

        preview = client.get(f"/api/v1/datasets/{dataset_id}/preview-request").json()
        assert preview["user"] == "shorter please"
        assert preview["history"] == [
            {"role": "user", "content": "summarize this"},
            {"role": "assistant", "content": "Long summary."},
        ]


def test_double_promote_of_identical_input_is_409(sqlite_engine) -> None:
    lines = "\n".join(
        json.dumps(_structured_item(f"dup-{i}")) for i in range(2)
    )  # identical inputs, distinct ids
    with TestClient(app) as client:
        client.post(
            "/api/v1/telemetry/upload",
            files={"file": ("t.jsonl", lines, "text/plain")},
        )
        exchanges = client.get("/api/v1/telemetry/inbox").json()["exchanges"]
        first = client.post(
            f"/api/v1/telemetry/exchanges/{exchanges[0]['id']}/promote", json={"lock": True}
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/telemetry/exchanges/{exchanges[1]['id']}/promote", json={"lock": True}
        )
        assert second.status_code == 409


def test_preview_of_malformed_chat_case_returns_400(sqlite_engine) -> None:
    from clean_evals.storage.db import CaseRow, DatasetRow, session_factory

    factory = session_factory()
    with factory() as session:
        ds = DatasetRow(
            name="broken-chat",
            version="v1",
            scorer="llm_judge",
            scorer_config={},
            request_shape="chat",
        )
        session.add(ds)
        session.flush()
        session.add(
            CaseRow(
                dataset_id=ds.id,
                case_id_external="c1",
                input_jsonb={"text": "no message field"},
                expected_jsonb=None,
                tags_jsonb=[],
                locked=False,
                metadata_jsonb={},
            )
        )
        session.commit()
        ds_id = ds.id
    with TestClient(app) as client:
        resp = client.get(f"/api/v1/datasets/{ds_id}/preview-request")
        assert resp.status_code == 400
        assert "message" in resp.json()["detail"]


def test_prompt_spec_refuses_chat_for_incompatible_cases(sqlite_engine) -> None:
    with TestClient(app) as client:
        up = client.post(
            "/api/v1/builder/upload",
            data={"name": "plain", "version": "v1", "scorer": "exact_match"},
            files={"file": ("inputs.csv", "id,text\nc1,hello\n", "text/csv")},
        )
        dataset_id = up.json()["dataset_id"]
        resp = client.patch(
            f"/api/v1/datasets/{dataset_id}/prompt-spec",
            json={"request_shape": "chat"},
        )
        assert resp.status_code == 400
        assert "message" in resp.json()["detail"]


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
