"""Pricing overrides, live model parsing, and feed proposals."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from clean_evals import pricing
from clean_evals.connectivity import _parse_models
from clean_evals.pricing import Price, effective_version, known_models, lookup
from clean_evals.pricing_feeds import _parse_litellm, _parse_openrouter, build_proposals
from clean_evals.web.app import app


@pytest.fixture
def override_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "pricing.yml"
    monkeypatch.setenv("CLEAN_EVALS_PRICING_FILE", str(path))
    return path


def test_override_wins_and_versions_change(override_file: Path) -> None:
    base = lookup("anthropic", "claude-haiku-4-5-20251001")
    assert base is not None
    assert effective_version() == pricing.PRICING_VERSION

    pricing.set_override(
        "anthropic", "claude-haiku-4-5-20251001", input_per_mtok=0.5, output_per_mtok=2.0
    )
    changed = lookup("anthropic", "claude-haiku-4-5-20251001")
    assert changed == Price(0.5, 2.0)
    assert effective_version().startswith(f"{pricing.PRICING_VERSION}+")

    assert pricing.remove_override("anthropic", "claude-haiku-4-5-20251001") is True
    assert lookup("anthropic", "claude-haiku-4-5-20251001") == base
    assert effective_version() == pricing.PRICING_VERSION


def test_override_adds_unknown_model(override_file: Path) -> None:
    assert lookup("openai", "gpt-new-2027-01-01") is None
    pricing.set_override("openai", "gpt-new-2027-01-01", input_per_mtok=1.0, output_per_mtok=3.0)
    assert lookup("openai", "gpt-new-2027-01-01") == Price(1.0, 3.0)
    assert ("openai", "gpt-new-2027-01-01") in known_models()


def test_parse_models_filters_noise() -> None:
    openai_body = {
        "data": [
            {"id": "gpt-4o-2024-11-20"},
            {"id": "gpt-4o-audio-preview"},
            {"id": "text-embedding-3-small"},
            {"id": "whisper-1"},
            {"id": "o1-2024-12-17"},
            {"id": "gpt-4o-latest"},
            {"id": "gpt-3.5-turbo-instruct"},
        ]
    }
    assert _parse_models("openai", openai_body) == ("gpt-4o-2024-11-20", "o1-2024-12-17")

    google_body = {
        "models": [
            {
                "name": "models/gemini-2.0-flash-001",
                "supportedGenerationMethods": ["generateContent"],
            },
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        ]
    }
    assert _parse_models("google", google_body) == ("gemini-2.0-flash-001",)


def test_feed_parsers_convert_per_token_to_per_mtok() -> None:
    litellm = _parse_litellm(
        {
            "gpt-4o-mini-2024-07-18": {
                "litellm_provider": "openai",
                "input_cost_per_token": 1.5e-07,
                "output_cost_per_token": 6e-07,
            },
            "gemini/gemini-2.0-flash-001": {
                "litellm_provider": "gemini",
                "input_cost_per_token": 1e-07,
                "output_cost_per_token": 4e-07,
            },
            "some-embedding": {"litellm_provider": "openai", "mode": "embedding"},
        }
    )
    assert litellm[("openai", "gpt-4o-mini-2024-07-18")] == Price(0.15, 0.6)
    assert litellm[("google", "gemini-2.0-flash-001")] == Price(0.1, 0.4)

    openrouter = _parse_openrouter(
        {
            "data": [
                {
                    "id": "anthropic/claude-sonnet-4-6",
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                },
                {
                    "id": "mistralai/mistral-large",
                    "pricing": {"prompt": "0.000002", "completion": "0.000006"},
                },
            ]
        }
    )
    assert openrouter == {("anthropic", "claude-sonnet-4-6"): Price(3.0, 15.0)}


def test_build_proposals_skips_matching_prices(override_file: Path) -> None:
    feed = {
        ("openai", "gpt-4o-mini-2024-07-18"): Price(0.15, 0.6),  # matches built-in
        ("openai", "gpt-4o-2024-11-20"): Price(2.0, 8.0),  # differs
        ("openai", "gpt-unknown"): Price(1.0, 2.0),  # not in catalog
    }
    catalog = [("openai", "gpt-4o-mini-2024-07-18"), ("openai", "gpt-4o-2024-11-20")]
    proposals = build_proposals(catalog, feed)
    assert [p.model for p in proposals] == ["gpt-4o-2024-11-20"]
    assert proposals[0].current_input == 2.5
    assert proposals[0].new_input == 2.0


@respx.mock
def test_pricing_endpoints(override_file: Path, sqlite_engine) -> None:
    with TestClient(app) as client:
        resp = client.put(
            "/api/v1/models/pricing",
            json={
                "provider": "openai",
                "model": "gpt-new-2027-01-01",
                "input_per_mtok": 1.0,
                "output_per_mtok": 3.0,
            },
        )
        assert resp.status_code == 200
        openai = next(p for p in resp.json() if p["provider"] == "openai")
        added = next(m for m in openai["models"] if m["id"] == "gpt-new-2027-01-01")
        assert added["overridden"] is True
        assert added["input_per_mtok"] == 1.0

        resp = client.delete(
            "/api/v1/models/pricing",
            params={"provider": "openai", "model": "gpt-new-2027-01-01"},
        )
        assert resp.status_code == 200

        resp = client.delete(
            "/api/v1/models/pricing",
            params={"provider": "openai", "model": "gpt-new-2027-01-01"},
        )
        assert resp.status_code == 404


@respx.mock
def test_refresh_and_apply(override_file: Path, sqlite_engine) -> None:
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=Response(200, json={"data": []})
    )
    respx.get(
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    ).mock(
        return_value=Response(
            200,
            json={
                "gpt-4o-2024-11-20": {
                    "litellm_provider": "openai",
                    "input_cost_per_token": 2e-06,
                    "output_cost_per_token": 8e-06,
                }
            },
        )
    )
    with TestClient(app) as client:
        proposals = client.post("/api/v1/models/pricing/refresh").json()
        assert proposals == [
            {
                "provider": "openai",
                "model": "gpt-4o-2024-11-20",
                "current_input": 2.5,
                "current_output": 10.0,
                "new_input": 2.0,
                "new_output": 8.0,
                "source": "litellm/openrouter",
            }
        ]

        resp = client.post(
            "/api/v1/models/pricing/apply",
            json={
                "items": [
                    {
                        "provider": "openai",
                        "model": "gpt-4o-2024-11-20",
                        "input_per_mtok": 2.0,
                        "output_per_mtok": 8.0,
                    }
                ]
            },
        )
        assert resp.status_code == 200
        assert lookup("openai", "gpt-4o-2024-11-20") == Price(2.0, 8.0)


@respx.mock
def test_live_models_merge_into_catalog(
    override_file: Path, sqlite_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "live-list-key-1")
    respx.get("https://api.anthropic.com/v1/models?limit=100").mock(
        return_value=Response(
            200,
            json={"data": [{"id": "claude-new-5-2027-01-01"}, {"id": "claude-haiku-4-5-20251001"}]},
        )
    )
    with TestClient(app) as client:
        providers = {p["provider"]: p for p in client.get("/api/v1/models").json()}
    anthropic = providers["anthropic"]
    assert anthropic["status"] == "connected"
    by_id = {m["id"]: m for m in anthropic["models"]}
    # Live-only model: selectable, no price yet.
    assert by_id["claude-new-5-2027-01-01"]["input_per_mtok"] is None
    assert by_id["claude-new-5-2027-01-01"]["listed"] is True
    # Known model listed live: priced and marked as listed.
    assert by_id["claude-haiku-4-5-20251001"]["listed"] is True
    assert by_id["claude-haiku-4-5-20251001"]["input_per_mtok"] == 0.8
    # Known model the provider did not list stays in the catalog.
    assert by_id["claude-sonnet-4-6"]["listed"] is False


@pytest.fixture
def exclusions_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "excluded-models.yml"
    monkeypatch.setenv("CLEAN_EVALS_EXCLUDED_MODELS_FILE", str(path))
    return path


@respx.mock
def test_exclusions_persist_and_hide_from_refresh(
    override_file: Path, exclusions_file: Path, sqlite_engine
) -> None:
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=Response(200, json={"data": []})
    )
    respx.get(
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    ).mock(
        return_value=Response(
            200,
            json={
                "gpt-4o-2024-11-20": {
                    "litellm_provider": "openai",
                    "input_cost_per_token": 2e-06,
                    "output_cost_per_token": 8e-06,
                }
            },
        )
    )
    with TestClient(app) as client:
        resp = client.put(
            "/api/v1/models/excluded",
            json={"provider": "openai", "model": "gpt-4o-2024-11-20", "excluded": True},
        )
        assert resp.status_code == 200
        openai = next(p for p in resp.json() if p["provider"] == "openai")
        flagged = next(m for m in openai["models"] if m["id"] == "gpt-4o-2024-11-20")
        assert flagged["excluded"] is True

        # The price refresh skips excluded models.
        assert client.post("/api/v1/models/pricing/refresh").json() == []

        # Include again.
        resp = client.put(
            "/api/v1/models/excluded",
            json={"provider": "openai", "model": "gpt-4o-2024-11-20", "excluded": False},
        )
        openai = next(p for p in resp.json() if p["provider"] == "openai")
        flagged = next(m for m in openai["models"] if m["id"] == "gpt-4o-2024-11-20")
        assert flagged["excluded"] is False


def test_deterministic_suggestion_picks_avoid_variants() -> None:
    from clean_evals.suggestions import _deterministic_picks

    tiers = {
        "cheap": [
            ("gpt-5-nano", 0.05),
            ("gpt-5-nano-2025-08-07", 0.05),
            ("gemini-2.0-flash-001", 0.1),
        ],
        "medium": [("gpt-4o-2024-11-20", 2.5), ("claude-sonnet-4-6", 3.0)],
        "expensive": [("claude-opus-4-7", 5.0)],
    }
    picks = _deterministic_picks(tiers)
    cheap = [p.model for p in picks if p.tier == "cheap"]
    assert cheap == ["gpt-5-nano", "gemini-2.0-flash-001"]
    assert [p.model for p in picks if p.tier == "expensive"] == ["claude-opus-4-7"]
    # An explanation is always present.
    assert all(p.reason for p in picks)
    assert picks[0].reason == "cheap tier, $0.05 per Mtok input"
