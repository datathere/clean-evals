"""End-to-end tests for stages 1-4 of the golden path (docs/docs/flow.md).

Exercises the whole flow against SQLite with a deterministic stub adapter:
upload -> prompt spec -> generate candidates -> rate -> pick golden ->
calibrate judge. No network, no queue.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Literal

import pytest
from fastapi.testclient import TestClient

from clean_evals.calibration import agreement_stats, few_shot_examples, render_rubric
from clean_evals.candidates import generate_candidates
from clean_evals.models import ModelResponse
from clean_evals.storage.db import session_factory
from clean_evals.web.app import app

MODEL_A = "claude-haiku-4-5-20251001"
MODEL_B = "gpt-4o-mini-2024-07-18"


class StubAdapter:
    """Echoes a canned answer per model; records what it was asked."""

    provider: ClassVar[str] = "stub"

    def __init__(self, answers: dict[str, str], cost: float = 0.001) -> None:
        self._answers = answers
        self._cost = cost
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt: str,
        model: str,
        *,
        temperature: float,
        seed: int | None,
        timeout_s: float,
        response_format: Literal["text", "json"] = "text",
        system: str | None = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "model": model, "system": system})
        content = self._answers.get(model, "answer")
        return ModelResponse(
            content=content,
            parsed=json.loads(content) if response_format == "json" else None,
            tokens_in=10,
            tokens_out=2,
            latency_ms=5,
            cost_usd=self._cost,
        )


class StubJudge:
    """Judge that scores 5 when the output matches its notion of good."""

    provider: ClassVar[str] = "stub"

    def __init__(self, good_output: str) -> None:
        self._good = good_output

    async def complete(
        self,
        prompt: str,
        model: str,
        *,
        temperature: float,
        seed: int | None,
        timeout_s: float,
        response_format: Literal["text", "json"] = "text",
        system: str | None = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelResponse:
        score = 5 if self._good in prompt.rsplit("OUTPUT:", maxsplit=1)[-1] else 2
        body = json.dumps({"score": score, "reason": "stub"})
        return ModelResponse(
            content=body,
            parsed={"score": score, "reason": "stub"},
            tokens_in=10,
            tokens_out=5,
            latency_ms=3,
            cost_usd=0.0001,
        )


@pytest.fixture
def dataset_id(sqlite_engine) -> int:
    """A templated dataset with two cases, uploaded through the real endpoint."""
    csv_body = "id,ticket\nt1,Charged twice\nt2,Change my email\n"
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/builder/upload",
            data={
                "name": "support",
                "version": "v1",
                "scorer": "exact_match",
                "request_shape": "templated",
                "system_prompt": "You are a support agent. Reply with only the category.",
            },
            files={"file": ("inputs.csv", csv_body, "text/csv")},
        )
        assert resp.status_code == 200
        return int(resp.json()["dataset_id"])


def test_prompt_spec_and_preview(dataset_id: int, sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.patch(
            f"/api/v1/datasets/{dataset_id}/prompt-spec",
            json={
                "request_shape": "templated",
                "system_prompt": "You are a support agent.",
                "shared_context": "Categories: billing, account.",
                "user_template": None,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["request_shape"] == "templated"

        resp = client.get(f"/api/v1/datasets/{dataset_id}/preview-request")
        assert resp.status_code == 200
        preview = resp.json()
        assert preview["system"] == "You are a support agent."
        assert "Categories: billing, account." in preview["user"]
        assert "Charged twice" in preview["user"]


def test_generate_rate_pick_flow(dataset_id: int, sqlite_engine) -> None:
    import asyncio

    stub = StubAdapter({MODEL_A: "billing", MODEL_B: "account"})
    job = asyncio.run(
        generate_candidates(
            session_factory(),
            dataset_id,
            [MODEL_A, MODEL_B],
            adapters={"anthropic": stub, "openai": stub},
        )
    )
    assert job.status == "done"
    assert job.done == 4  # 2 cases x 2 models
    # System prompt travelled in the system role, not the user message.
    assert all(c["system"] and "support agent" in c["system"] for c in stub.calls)
    assert all("support agent" not in c["prompt"] for c in stub.calls)

    with TestClient(app) as client:
        cands = client.get(f"/api/v1/datasets/{dataset_id}/candidates").json()
        assert len(cands) == 4

        # Rate everything: MODEL_A good, MODEL_B poor.
        for cand in cands:
            rating = 5 if cand["model"] == MODEL_A else 2
            resp = client.put(
                f"/api/v1/datasets/{dataset_id}/candidates/{cand['id']}/rating",
                json={"rating": rating, "feedback": "wrong category" if rating == 2 else None},
            )
            assert resp.status_code == 200

        # Pick MODEL_A's output as golden for the first case.
        best = next(c for c in cands if c["model"] == MODEL_A)
        resp = client.post(
            f"/api/v1/datasets/{dataset_id}/cases/{best['case_id']}/golden",
            json={"candidate_id": best["id"]},
        )
        assert resp.status_code == 200
        picked = resp.json()
        assert picked["locked"] is True
        assert picked["expected"] == {"text": "billing"}

        # Repeating the same pick is a no-op; a different answer conflicts.
        resp = client.post(
            f"/api/v1/datasets/{dataset_id}/cases/{best['case_id']}/golden",
            json={"candidate_id": best["id"]},
        )
        assert resp.status_code == 200
        resp = client.post(
            f"/api/v1/datasets/{dataset_id}/cases/{best['case_id']}/golden",
            json={"expected": {"text": "other"}},
        )
        assert resp.status_code == 409

        # Progress shows up on the dataset.
        ds = client.get(f"/api/v1/datasets/{dataset_id}").json()
        assert ds["locked_count"] == 1
        assert ds["case_count"] == 2


def test_calibrate_measures_agreement(dataset_id: int, sqlite_engine) -> None:
    import asyncio

    from clean_evals.calibration import calibrate

    stub = StubAdapter({MODEL_A: "billing", MODEL_B: "account"})
    asyncio.run(
        generate_candidates(
            session_factory(),
            dataset_id,
            [MODEL_A, MODEL_B],
            adapters={"anthropic": stub, "openai": stub},
        )
    )
    with TestClient(app) as client:
        cands = client.get(f"/api/v1/datasets/{dataset_id}/candidates").json()
        for cand in cands:
            rating = 5 if cand["model"] == MODEL_A else 2
            client.put(
                f"/api/v1/datasets/{dataset_id}/candidates/{cand['id']}/rating",
                json={"rating": rating, "feedback": "bad" if rating == 2 else "good"},
            )

    # Judge agrees with the human: "billing" outputs are the good ones.
    judge = StubJudge(good_output="billing")
    config = asyncio.run(
        calibrate(
            session_factory(),
            dataset_id,
            judge_model=MODEL_A,
            adapters={"anthropic": judge},
        )
    )
    summary = config.agreement_jsonb["summary"]
    assert summary["n"] == 4
    assert summary["exact"] == 1.0
    assert summary["kappa"] == 1.0

    with TestClient(app) as client:
        resp = client.get(f"/api/v1/datasets/{dataset_id}/judge")
        assert resp.status_code == 200
        assert resp.json()["version"] == config.version


def test_calibrate_requires_ratings(dataset_id: int, sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/datasets/{dataset_id}/judge/calibrate",
            json={"judge_model": MODEL_A},
        )
        assert resp.status_code == 400


def test_agreement_stats_math() -> None:
    perfect = agreement_stats([(1, 1), (3, 3), (5, 5)])
    assert perfect["exact"] == 1.0
    assert perfect["kappa"] == 1.0

    off_by_one = agreement_stats([(4, 5), (2, 1), (3, 4), (5, 4)])
    assert off_by_one["exact"] == 0.0
    assert off_by_one["within_one"] == 1.0

    assert agreement_stats([])["n"] == 0


def test_few_shot_spreads_ratings_and_excludes_target_case() -> None:
    from clean_evals.calibration import RatedOutput

    pool = [
        RatedOutput(
            candidate_id=i,
            case_pk=i % 3,
            case_id=f"c{i % 3}",
            model="m",
            case_input={"q": str(i)},
            expected=None,
            output=f"out{i}",
            human_rating=(i % 5) + 1,
            feedback="fb" if i % 2 == 0 else None,
        )
        for i in range(9)
    ]
    examples = few_shot_examples(pool, exclude_case_pk=0)
    assert examples
    assert all(ex["input"]["q"] != "0" for ex in examples)  # case 0 excluded
    rubric = render_rubric("BASE", examples)
    assert "Reviewer score:" in rubric


def test_unlock_and_new_version(dataset_id: int, sqlite_engine, tmp_artifact_dir) -> None:

    from clean_evals.eval_service import execute_run
    from clean_evals.models import RunConfig

    with TestClient(app) as client:
        cases = client.get(f"/api/v1/datasets/{dataset_id}/cases").json()
        first = cases[0]
        # Lock a golden answer, then unlock it: fine while no runs exist.
        client.patch(
            f"/api/v1/datasets/{dataset_id}/cases/{first['id']}",
            json={"expected": {"text": "billing"}, "rev": first["rev"]},
        )
        client.post(f"/api/v1/datasets/{dataset_id}/cases/{first['id']}/lock")
        resp = client.post(f"/api/v1/datasets/{dataset_id}/cases/{first['id']}/unlock")
        assert resp.status_code == 200
        assert resp.json()["locked"] is False
        client.post(f"/api/v1/datasets/{dataset_id}/cases/{first['id']}/lock")

    # A run now references the dataset.
    stub = StubAdapter({MODEL_A: "billing"})
    execute_run(
        dataset_id,
        RunConfig(models=[MODEL_A], retries=0, max_cost_usd=1.0),
        triggered_by="web",
        adapters={"anthropic": stub},
    )

    with TestClient(app) as client:
        resp = client.post(f"/api/v1/datasets/{dataset_id}/cases/{first['id']}/unlock")
        assert resp.status_code == 409

        # New version: cases carried over, unlocked, editable.
        resp = client.post(f"/api/v1/datasets/{dataset_id}/versions")
        assert resp.status_code == 201
        clone = resp.json()
        assert clone["version"] == "v2"
        assert clone["name"] == "support"
        assert clone["system_prompt"]
        v2_cases = client.get(f"/api/v1/datasets/{clone['id']}/cases").json()
        assert len(v2_cases) == 2
        assert all(not c["locked"] for c in v2_cases)
        carried = next(c for c in v2_cases if c["case_id_external"] == first["case_id_external"])
        assert carried["expected"] == {"text": "billing"}


def test_dataset_settings_edit_and_guard(dataset_id: int, sqlite_engine, tmp_artifact_dir) -> None:
    from clean_evals.eval_service import execute_run
    from clean_evals.models import RunConfig

    with TestClient(app) as client:
        resp = client.patch(
            f"/api/v1/datasets/{dataset_id}/settings",
            json={
                "system_prompt": "Classify the ticket. One word.",
                "scorer_config": {"field": "label"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["system_prompt"] == "Classify the ticket. One word."
        assert body["scorer_config"] == {"field": "label"}

        # Invalid scorer config is rejected.
        resp = client.patch(
            f"/api/v1/datasets/{dataset_id}/settings",
            json={"scorer_config": {"pass_threshold": "not-a-number"}},
        )
        assert resp.status_code == 400

    execute_run(
        dataset_id,
        RunConfig(models=[MODEL_A], retries=0, max_cost_usd=1.0),
        triggered_by="web",
        adapters={"anthropic": StubAdapter({MODEL_A: "billing"})},
    )
    with TestClient(app) as client:
        resp = client.patch(
            f"/api/v1/datasets/{dataset_id}/settings",
            json={"system_prompt": "changed"},
        )
        assert resp.status_code == 409
