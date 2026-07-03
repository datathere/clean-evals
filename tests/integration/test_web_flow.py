"""The full golden path through the web API against the fake provider.

Upload -> generate candidates -> lock golden answers -> run eval ->
leaderboard, with no API cost. Exercises the runner, the persisted job
state, and the inline-run path end to end.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from clean_evals.web.app import app

pytestmark = pytest.mark.integration

MODEL = "local/fake-1"


def _poll(client: TestClient, url: str, done: set[str], *, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(url).json()
        if body["status"] in done:
            return body
        time.sleep(0.1)
    raise AssertionError(f"{url} did not reach {done}; last={body}")


def test_golden_path_end_to_end(migrated_sqlite: str, fake_openai_server: str) -> None:
    with TestClient(app) as client:
        # 1. Upload inputs.
        csv_body = (
            "id,text\n"
            "c1,I love this product\n"
            "c2,This is terrible and I hate it\n"
            "c3,The package arrived\n"
        )
        up = client.post(
            "/api/v1/builder/upload",
            data={"name": "sentiment", "version": "v1", "scorer": "exact_match"},
            files={"file": ("inputs.csv", csv_body, "text/csv")},
        )
        assert up.status_code == 200, up.text
        dataset_id = up.json()["dataset_id"]

        # 2. Generate candidates from the fake model.
        gen = client.post(
            f"/api/v1/datasets/{dataset_id}/candidates",
            json={"models": [MODEL], "max_cost_usd": 1.0, "temperature": 0.0},
        )
        assert gen.status_code == 202, gen.text
        status = _poll(
            client,
            f"/api/v1/datasets/{dataset_id}/candidates/status",
            {"done", "error", "aborted_cost"},
        )
        assert status["status"] == "done", status
        assert status["candidate_count"] == 3

        candidates = client.get(f"/api/v1/datasets/{dataset_id}/candidates").json()
        assert len(candidates) == 3

        # 3. Lock a golden answer per case (pick the generated candidate).
        cases = client.get(f"/api/v1/datasets/{dataset_id}/cases").json()
        assert len(cases) == 3
        by_case = {c["case_id"]: c for c in candidates}
        for case in cases:
            cand = by_case[case["id"]]
            pick = client.post(
                f"/api/v1/datasets/{dataset_id}/cases/{case['id']}/golden",
                json={"expected": {"text": cand["content"]}},
            )
            assert pick.status_code in (200, 201), pick.text

        ds = client.get(f"/api/v1/datasets/{dataset_id}").json()
        assert ds["locked_count"] == 3

        # 4. Run the eval inline.
        run = client.post(
            "/api/v1/runs",
            json={
                "dataset_id": dataset_id,
                "config": {"models": [MODEL], "max_cost_usd": 1.0, "temperature": 0.0},
                "mode": "inline",
            },
        )
        assert run.status_code == 202, run.text
        inline = _poll(
            client,
            f"/api/v1/runs/inline-status/{dataset_id}",
            {"done", "error"},
        )
        assert inline["status"] == "done", inline
        run_id = inline["run_id"]
        assert run_id

        # 5. Results: the fake model matches its own locked answers, so it
        # scores perfectly.
        detail = client.get(f"/api/v1/runs/{run_id}").json()
        assert detail["dataset"] == "sentiment"
        summary = detail["summary"][MODEL]
        assert summary["cases_run"] == 3
        assert summary["cases_passed"] == 3
        assert summary["score_mean"] == 1.0
        assert summary["total_cost_usd"] == 0.0  # local models are free

        recs = client.get(f"/api/v1/runs/{run_id}/recommendations").json()
        assert any(r["model"] == MODEL for r in recs)


def test_inline_run_on_unlocked_dataset_scores_zero(
    migrated_sqlite: str, fake_openai_server: str
) -> None:
    """A run with no golden answers completes and scores 0 (no crash)."""
    with TestClient(app) as client:
        up = client.post(
            "/api/v1/builder/upload",
            data={"name": "unlocked", "version": "v1", "scorer": "exact_match"},
            files={"file": ("i.csv", "id,text\nc1,hello\n", "text/csv")},
        )
        dataset_id = up.json()["dataset_id"]
        client.post(
            "/api/v1/runs",
            json={
                "dataset_id": dataset_id,
                "config": {"models": [MODEL], "max_cost_usd": 1.0},
                "mode": "inline",
            },
        )
        inline = _poll(client, f"/api/v1/runs/inline-status/{dataset_id}", {"done", "error"})
        assert inline["status"] == "done", inline
        detail = client.get(f"/api/v1/runs/{inline['run_id']}").json()
        assert detail["summary"][MODEL]["score_mean"] == 0.0


def test_models_catalog_lists_live_local_models(
    migrated_sqlite: str, fake_openai_server: str
) -> None:
    """With the fake server reachable, the catalog probes it and lists its
    models under a connected 'local' provider."""
    with TestClient(app) as client:
        providers = client.get("/api/v1/models").json()
        local = next((p for p in providers if p["provider"] == "local"), None)
        assert local is not None
        assert local["status"] == "connected"
        assert any(m["id"] == "local/fake-1" for m in local["models"])


def test_generation_status_survives_a_fresh_client(
    migrated_sqlite: str, fake_openai_server: str
) -> None:
    """Job status lives in the DB: a brand-new client (no shared process
    memory with the one that ran generation) still sees the result."""
    with TestClient(app) as client:
        up = client.post(
            "/api/v1/builder/upload",
            data={"name": "persisted", "version": "v1", "scorer": "exact_match"},
            files={"file": ("inputs.csv", "id,text\nc1,hello\n", "text/csv")},
        )
        dataset_id = up.json()["dataset_id"]
        client.post(
            f"/api/v1/datasets/{dataset_id}/candidates",
            json={"models": [MODEL], "max_cost_usd": 1.0},
        )
        _poll(
            client,
            f"/api/v1/datasets/{dataset_id}/candidates/status",
            {"done", "error"},
        )

    # A second client shares only the database, not in-process state.
    with TestClient(app) as other:
        status = other.get(f"/api/v1/datasets/{dataset_id}/candidates/status").json()
        assert status["status"] == "done"
        assert status["candidate_count"] == 1
