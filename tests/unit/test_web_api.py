"""FastAPI smoke tests using the test client.

Uses SQLite + in-process schema. Doesn't exercise SSE or Celery.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from clean_evals.web.app import app


def test_health(sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_list_datasets_empty(sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/datasets")
        assert resp.status_code == 200
        assert resp.json() == []


def test_get_run_404(sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.get("/api/v1/runs/r_does_not_exist")
        assert resp.status_code == 404


def test_builder_upload_csv(sqlite_engine) -> None:
    csv_body = "id,prompt\nc1,Hello\nc2,World\n"
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/builder/upload",
            data={"name": "ds_test", "version": "v1", "scorer": "exact_match"},
            files={"file": ("inputs.csv", csv_body, "text/csv")},
        )
        assert resp.status_code == 200
        out = resp.json()
        assert out["case_count"] == 2
        ds_id = out["dataset_id"]

        resp = client.get(f"/api/v1/datasets/{ds_id}/cases")
        assert resp.status_code == 200
        cases = resp.json()
        assert len(cases) == 2
        assert cases[0]["case_id_external"] == "c1"
