"""Model catalog endpoint (live-verified) + inline (no-queue) eval execution."""

from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from clean_evals.eval_service import execute_run
from clean_evals.models import RunConfig
from clean_evals.web.app import app

from .test_goldenpath import MODEL_A, StubAdapter

_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"


@respx.mock
def test_connected_means_verified_not_just_key_present(
    sqlite_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "verified-key-1")
    respx.get(_ANTHROPIC_MODELS_URL).mock(return_value=Response(200, json={"data": []}))
    with TestClient(app) as client:
        providers = {p["provider"]: p for p in client.get("/api/v1/models").json()}

    assert providers["anthropic"]["status"] == "connected"
    assert providers["anthropic"]["connected"] is True
    # No key at all — no network attempt, honestly reported.
    assert providers["openai"]["status"] == "not_configured"
    assert providers["openai"]["connected"] is False
    assert providers["openai"]["env_var"] == "OPENAI_API_KEY"
    anthropic_models = {m["id"] for m in providers["anthropic"]["models"]}
    assert "claude-haiku-4-5-20251001" in anthropic_models
    haiku = next(
        m for m in providers["anthropic"]["models"] if m["id"] == "claude-haiku-4-5-20251001"
    )
    assert haiku["input_per_mtok"] > 0


@respx.mock
def test_rejected_key_is_not_connected(sqlite_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-key-1")
    respx.get(_ANTHROPIC_MODELS_URL).mock(return_value=Response(401, json={"error": "auth"}))
    with TestClient(app) as client:
        providers = {p["provider"]: p for p in client.get("/api/v1/models").json()}

    assert providers["anthropic"]["status"] == "invalid_key"
    assert providers["anthropic"]["connected"] is False


@respx.mock
def test_provider_outage_reports_unreachable(
    sqlite_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    monkeypatch.setenv("ANTHROPIC_API_KEY", "timeout-key-1")
    respx.get(_ANTHROPIC_MODELS_URL).mock(side_effect=httpx.ConnectError("down"))
    with TestClient(app) as client:
        providers = {p["provider"]: p for p in client.get("/api/v1/models").json()}

    assert providers["anthropic"]["status"] == "unreachable"
    assert providers["anthropic"]["connected"] is False


def _golden_dataset(client: TestClient) -> int:
    csv_body = "id,ticket\nt1,Charged twice\nt2,Change my email\n"
    resp = client.post(
        "/api/v1/builder/upload",
        data={
            "name": "triage",
            "version": "v1",
            "scorer": "exact_match",
            "request_shape": "templated",
            "system_prompt": "Classify the ticket. Reply with only the category.",
        },
        files={"file": ("inputs.csv", csv_body, "text/csv")},
    )
    ds_id = int(resp.json()["dataset_id"])
    cases = client.get(f"/api/v1/datasets/{ds_id}/cases").json()
    for case in cases:
        client.patch(
            f"/api/v1/datasets/{ds_id}/cases/{case['id']}",
            json={"expected": {"text": "billing"}, "rev": case["rev"]},
        )
        client.post(f"/api/v1/datasets/{ds_id}/cases/{case['id']}/lock")
    return ds_id


def test_execute_run_persists_inline(sqlite_engine, tmp_artifact_dir) -> None:
    with TestClient(app) as client:
        ds_id = _golden_dataset(client)

    stub = StubAdapter({MODEL_A: "billing"})
    run_id = execute_run(
        ds_id,
        RunConfig(models=[MODEL_A], retries=0, max_cost_usd=1.0),
        triggered_by="web",
        adapters={"anthropic": stub},
    )
    assert run_id.startswith("r_")
    # System prompt reached the adapter through the system role.
    assert all(c["system"] for c in stub.calls)

    with TestClient(app) as client:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        assert run["status"] == "done"
        assert run["summary"][MODEL_A]["cases_run"] == 2
        assert run["summary"][MODEL_A]["score_mean"] == 1.0


def test_inline_status_idle(sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/runs/inline-status/9999")
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"
