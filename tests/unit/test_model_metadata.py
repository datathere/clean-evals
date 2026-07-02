"""OpenRouter model metadata: parsing, caching, catalog enrichment."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from clean_evals import model_metadata as mm
from clean_evals import pricing
from clean_evals.capabilities import REASONING_EFFORTS
from clean_evals.web.app import app

_BODY = {
    "data": [
        {
            "id": "openai/gpt-5",
            "description": "OpenAI's flagship reasoning model.",
            "context_length": 400000,
            "supported_parameters": ["max_tokens", "reasoning", "seed", "response_format"],
        },
        {
            "id": "anthropic/claude-sonnet-5",
            "description": "Anthropic's balanced model.",
            "context_length": 1000000,
            "supported_parameters": ["max_tokens", "temperature", "reasoning"],
        },
        {"id": "mistralai/mistral-large", "description": "Not a direct provider."},
        {"id": "openai/gpt-4o", "supported_parameters": []},
        "garbage-entry",
    ]
}


def test_parse_maps_direct_providers_only() -> None:
    table = mm.parse_metadata(_BODY)
    assert ("openai", "gpt-5") in table
    assert ("anthropic", "claude-sonnet-5") in table
    assert not any(p not in ("openai", "anthropic", "google") for p, _ in table)


def test_parse_extracts_definition_fields() -> None:
    meta = mm.parse_metadata(_BODY)[("openai", "gpt-5")]
    assert meta.description == "OpenAI's flagship reasoning model."
    assert meta.context_length == 400000
    assert "reasoning" in meta.supported_parameters


def test_capabilities_come_from_supported_parameters() -> None:
    table = mm.parse_metadata(_BODY)
    gpt5 = table[("openai", "gpt-5")].capabilities("openai")
    assert gpt5 is not None
    assert gpt5.supports_temperature is False
    assert gpt5.supports_seed is True
    assert gpt5.reasoning_efforts == REASONING_EFFORTS
    sonnet = table[("anthropic", "claude-sonnet-5")].capabilities("anthropic")
    assert sonnet is not None
    assert sonnet.supports_temperature is True
    assert sonnet.supports_seed is False


def test_effort_offered_only_when_the_adapter_can_send_it() -> None:
    """OpenRouter reports "reasoning" for Anthropic models, but our
    Anthropic adapter has no parameter to send an effort level through."""
    sonnet = mm.parse_metadata(_BODY)[("anthropic", "claude-sonnet-5")]
    caps = sonnet.capabilities("anthropic")
    assert caps is not None
    assert caps.reasoning_efforts == ()


def test_no_supported_parameters_defers_to_rules() -> None:
    assert mm.parse_metadata(_BODY)[("openai", "gpt-4o")].capabilities("openai") is None


def test_lookup_matches_dated_provider_ids() -> None:
    """Anthropic and OpenAI list dated snapshots; OpenRouter names the model."""
    table = mm.parse_metadata(
        {
            "data": [
                {"id": "anthropic/claude-sonnet-4.5", "description": "Sonnet."},
                {"id": "openai/gpt-4o", "description": "Omni."},
            ]
        }
    )
    hit = mm.lookup(table, "anthropic", "claude-sonnet-4-5-20250929")
    assert hit is not None
    assert hit.description == "Sonnet."
    hit = mm.lookup(table, "openai", "gpt-4o-2024-08-06")
    assert hit is not None
    assert hit.description == "Omni."
    assert mm.lookup(table, "openai", "gpt-4o-mini") is None


def test_undated_entry_wins_over_snapshot() -> None:
    entries = [
        {"id": "openai/gpt-4o", "description": "The model."},
        {"id": "openai/gpt-4o-2024-08-06", "description": "A snapshot."},
    ]
    for data in (entries, list(reversed(entries))):
        table = mm.parse_metadata({"data": data})
        assert table[("openai", "gpt-4o")].description == "The model."


@respx.mock
@pytest.mark.anyio
async def test_fetch_failure_returns_empty_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mm, "_cache", None)
    respx.get(mm.OPENROUTER_MODELS_URL).mock(side_effect=httpx.ConnectError("down"))
    assert await mm.model_metadata() == {}


@respx.mock
@pytest.mark.anyio
async def test_fetch_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mm, "_cache", None)
    route = respx.get(mm.OPENROUTER_MODELS_URL).mock(return_value=Response(200, json=_BODY))
    first = await mm.model_metadata()
    second = await mm.model_metadata()
    assert first == second
    assert route.call_count == 1


@respx.mock
def test_catalog_carries_definitions(monkeypatch: pytest.MonkeyPatch, sqlite_engine) -> None:
    monkeypatch.setattr(mm, "_cache", None)
    respx.get(mm.OPENROUTER_MODELS_URL).mock(return_value=Response(200, json=_BODY))
    # Overrides are how gpt-5 enters the catalog here: with no API keys the
    # provider reports no live list, and the built-in table may not carry it.
    pricing.set_override("openai", "gpt-5", input_per_mtok=1.25, output_per_mtok=10.0)
    with TestClient(app) as client:
        providers = client.get("/api/v1/models").json()
    openai = next(p for p in providers if p["provider"] == "openai")
    gpt5 = next(m for m in openai["models"] if m["id"] == "gpt-5")
    assert gpt5["description"] == "OpenAI's flagship reasoning model."
    assert gpt5["context_length"] == 400000
    assert gpt5["capabilities"]["supports_temperature"] is False
    assert gpt5["capabilities"]["reasoning_efforts"] == list(REASONING_EFFORTS)
