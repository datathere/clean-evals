"""Adapter HTTP behaviour, mocked via httpx.MockTransport.

These tests prove the wire shapes — they never hit real APIs.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from clean_evals.adapters.anthropic import AnthropicAdapter
from clean_evals.adapters.google import GoogleAdapter
from clean_evals.adapters.local import LocalAdapter
from clean_evals.adapters.openai import OpenAIAdapter
from clean_evals.adapters.openrouter import OpenRouterAdapter
from clean_evals.errors import ProviderError, RateLimited


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_happy_path() -> None:
    payload = {
        "id": "msg_1",
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "claude-3-5-sonnet-20241022"
        assert request.headers["x-api-key"] == "test-key"
        return httpx.Response(200, json=payload)

    adapter = AnthropicAdapter(api_key="test-key", client=_client(httpx.MockTransport(handler)))
    resp = await adapter.complete(
        prompt="hi", model="claude-3-5-sonnet-20241022", temperature=0.0, seed=1, timeout_s=10
    )
    await adapter.aclose()
    assert resp.content == "hello"
    assert resp.tokens_in == 10
    assert resp.tokens_out == 3
    assert resp.cost_usd > 0


@pytest.mark.asyncio
async def test_anthropic_rate_limited() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.05"}, json={"error": "rate"})

    adapter = AnthropicAdapter(api_key="test-key", client=_client(httpx.MockTransport(handler)))
    with pytest.raises(RateLimited) as ei:
        await adapter.complete(
            prompt="x",
            model="claude-3-5-sonnet-20241022",
            temperature=0.0,
            seed=None,
            timeout_s=5,
        )
    assert ei.value.retry_after_s == pytest.approx(0.05)
    await adapter.aclose()


@pytest.mark.asyncio
async def test_anthropic_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    adapter = AnthropicAdapter(api_key="k", client=_client(httpx.MockTransport(handler)))
    with pytest.raises(ProviderError):
        await adapter.complete(
            prompt="x",
            model="claude-3-5-sonnet-20241022",
            temperature=0.0,
            seed=None,
            timeout_s=5,
        )
    await adapter.aclose()


@pytest.mark.asyncio
async def test_anthropic_rejects_floating_alias() -> None:
    adapter = AnthropicAdapter(api_key="k")
    with pytest.raises(ProviderError):
        await adapter.complete(
            prompt="x",
            model="claude-3-5-sonnet-latest",
            temperature=0.0,
            seed=None,
            timeout_s=5,
        )
    await adapter.aclose()


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_json_mode_parses() -> None:
    payload: dict[str, Any] = {
        "choices": [{"message": {"content": '{"x": 1}'}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("response_format") == {"type": "json_object"}
        return httpx.Response(200, json=payload)

    adapter = OpenAIAdapter(api_key="k", client=_client(httpx.MockTransport(handler)))
    resp = await adapter.complete(
        prompt="extract",
        model="gpt-4o-mini-2024-07-18",
        temperature=0.0,
        seed=42,
        timeout_s=5,
        response_format="json",
    )
    await adapter.aclose()
    assert resp.parsed == {"x": 1}


@pytest.mark.asyncio
async def test_openai_reasoning_model_payload() -> None:
    """o-series calls omit temperature and carry effort + token cap."""
    payload: dict[str, Any] = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "temperature" not in body
        assert body["reasoning_effort"] == "high"
        assert body["max_completion_tokens"] == 2048
        return httpx.Response(200, json=payload)

    adapter = OpenAIAdapter(api_key="k", client=_client(httpx.MockTransport(handler)))
    await adapter.complete(
        prompt="think",
        model="o1-2024-12-17",
        temperature=0.0,
        seed=42,
        timeout_s=5,
        reasoning_effort="high",
        max_output_tokens=2048,
    )
    await adapter.aclose()


@pytest.mark.asyncio
async def test_anthropic_retries_without_temperature() -> None:
    """Models that reject temperature (opus 4.7+) succeed on the retry."""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "temperature" in body:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "`temperature` is deprecated for this model.",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "billing"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    adapter = AnthropicAdapter(api_key="k", client=_client(httpx.MockTransport(handler)))
    # claude-3-5-* predates the deprecation, so the rules still send
    # temperature; the retry path must recover.
    resp = await adapter.complete(
        prompt="classify",
        model="claude-3-5-sonnet-20241022",
        temperature=0.0,
        seed=None,
        timeout_s=5,
    )
    await adapter.aclose()
    assert resp.content == "billing"
    assert len(calls) == 2
    assert "temperature" in calls[0]
    assert "temperature" not in calls[1]


@pytest.mark.asyncio
async def test_anthropic_known_no_temperature_models_skip_it() -> None:
    """Opus 4.7+ and the 5 family never send temperature at all."""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    adapter = AnthropicAdapter(api_key="k", client=_client(httpx.MockTransport(handler)))
    for model in ("claude-opus-4-7", "claude-fable-5", "claude-sonnet-5"):
        await adapter.complete(prompt="x", model=model, temperature=0.0, seed=None, timeout_s=5)
    await adapter.aclose()
    assert all("temperature" not in c for c in calls)


def test_capabilities_rules() -> None:
    from clean_evals.capabilities import capabilities

    o1 = capabilities("openai", "o1-2024-12-17")
    assert o1.supports_temperature is False
    assert o1.reasoning_efforts == ("low", "medium", "high")
    assert o1.supports_seed is True

    gpt = capabilities("openai", "gpt-4o-mini-2024-07-18")
    assert gpt.supports_temperature is True
    assert gpt.reasoning_efforts == ()

    claude = capabilities("anthropic", "claude-haiku-4-5-20251001")
    assert claude.supports_temperature is True
    assert claude.supports_seed is False

    # Anthropic deprecated temperature starting with the opus 4.7 generation.
    for model in ("claude-opus-4-7", "claude-opus-4-8", "claude-fable-5", "claude-sonnet-5"):
        assert capabilities("anthropic", model).supports_temperature is False


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_happy_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "gemini-1.5-pro-002" in str(request.url)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "hello"}]}},
                ],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2},
            },
        )

    adapter = GoogleAdapter(api_key="k", client=_client(httpx.MockTransport(handler)))
    resp = await adapter.complete(
        prompt="x",
        model="gemini-1.5-pro-002",
        temperature=0.0,
        seed=None,
        timeout_s=5,
    )
    await adapter.aclose()
    assert resp.content == "hello"


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_uses_provider_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_cost": 0.0123},
            },
        )

    adapter = OpenRouterAdapter(api_key="k", client=_client(httpx.MockTransport(handler)))
    resp = await adapter.complete(
        prompt="x", model="some/upstream-2024-01", temperature=0.0, seed=1, timeout_s=5
    )
    await adapter.aclose()
    assert resp.cost_usd == 0.0123


# ---------------------------------------------------------------------------
# Local (OpenAI-compatible endpoints)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_happy_path_strips_prefix_and_costs_zero() -> None:
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://gpu-box:8000/v1/chat/completions"
        body = json.loads(request.content)
        # The local/ routing prefix never reaches the server.
        assert body["model"] == "llama3.2"
        assert body["temperature"] == 0.0
        assert body["seed"] == 7
        # No token configured: no authorization header.
        assert "authorization" not in request.headers
        return httpx.Response(200, json=payload)

    adapter = LocalAdapter(
        base_url="http://gpu-box:8000/v1", client=_client(httpx.MockTransport(handler))
    )
    resp = await adapter.complete(
        prompt="x", model="local/llama3.2", temperature=0.0, seed=7, timeout_s=5
    )
    await adapter.aclose()
    assert resp.content == "hi"
    assert resp.tokens_in == 12
    assert resp.tokens_out == 4
    assert resp.cost_usd == 0.0


@pytest.mark.asyncio
async def test_local_sends_bearer_token_when_configured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-local"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    adapter = LocalAdapter(
        base_url="http://localhost:1234/v1",
        api_key="sk-local",
        client=_client(httpx.MockTransport(handler)),
    )
    resp = await adapter.complete(
        prompt="x", model="local/qwen2.5-coder:14b", temperature=0.0, seed=None, timeout_s=5
    )
    await adapter.aclose()
    assert resp.content == "ok"


@pytest.mark.asyncio
async def test_local_defaults_to_ollama_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLEAN_EVALS_LOCAL_BASE_URL", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:11434/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    adapter = LocalAdapter(client=_client(httpx.MockTransport(handler)))
    await adapter.complete(
        prompt="x", model="local/llama3.2", temperature=0.0, seed=None, timeout_s=5
    )
    await adapter.aclose()


@pytest.mark.asyncio
async def test_local_json_mode_parses_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"label": "billing"}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            },
        )

    adapter = LocalAdapter(
        base_url="http://localhost:11434/v1", client=_client(httpx.MockTransport(handler))
    )
    resp = await adapter.complete(
        prompt="x",
        model="local/llama3.2",
        temperature=0.0,
        seed=None,
        timeout_s=5,
        response_format="json",
    )
    await adapter.aclose()
    assert resp.parsed == {"label": "billing"}


@pytest.mark.asyncio
async def test_local_accepts_latest_style_tags() -> None:
    """Ollama's default tag is :latest; the dated-snapshot rule is hosted-only."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "llama3.2:latest"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    adapter = LocalAdapter(
        base_url="http://localhost:11434/v1", client=_client(httpx.MockTransport(handler))
    )
    resp = await adapter.complete(
        prompt="x", model="local/llama3.2:latest", temperature=0.0, seed=None, timeout_s=5
    )
    await adapter.aclose()
    assert resp.content == "ok"


@pytest.mark.asyncio
async def test_local_sends_system_message_and_prompt() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"] == [
            {"role": "system", "content": "You are a classifier."},
            {"role": "user", "content": "Context here.\n\nThe ticket."},
        ]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    adapter = LocalAdapter(
        base_url="http://localhost:11434/v1", client=_client(httpx.MockTransport(handler))
    )
    resp = await adapter.complete(
        prompt="Context here.\n\nThe ticket.",
        model="local/llama3.2",
        temperature=0.0,
        seed=None,
        timeout_s=5,
        system="You are a classifier.",
    )
    await adapter.aclose()
    assert resp.content == "ok"
