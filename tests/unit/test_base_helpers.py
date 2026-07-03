"""Shared adapter helpers in adapters/_base."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from clean_evals.adapters._base import (
    env_or_raise,
    parse_json_or_raise,
    parse_retry_after,
    post_json,
    reject_floating_alias,
)
from clean_evals.errors import ProviderError, ProviderTimeout, RateLimited, SchemaInvalidResponse


def test_env_or_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_KEY", "v")
    assert env_or_raise("SOME_KEY") == "v"
    monkeypatch.delenv("SOME_KEY", raising=False)
    with pytest.raises(ProviderError):
        env_or_raise("SOME_KEY")


def test_parse_retry_after_seconds_and_none() -> None:
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("garbage") is None


def test_parse_retry_after_http_date() -> None:
    future = datetime.now(UTC) + timedelta(seconds=30)
    got = parse_retry_after(format_datetime(future))
    assert got is not None
    assert 20 <= got <= 40


def test_reject_floating_alias() -> None:
    reject_floating_alias("gpt-4o-2024-11-20")  # no raise
    with pytest.raises(ProviderError):
        reject_floating_alias("gpt-4o-latest")
    with pytest.raises(ProviderError):
        reject_floating_alias("latest")


def test_parse_json_or_raise_strips_fence() -> None:
    assert parse_json_or_raise('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(SchemaInvalidResponse):
        parse_json_or_raise("not json")
    with pytest.raises(SchemaInvalidResponse):
        parse_json_or_raise("[1, 2, 3]")  # array, not object


@pytest.mark.asyncio
async def test_post_json_maps_errors() -> None:
    def rate_limited(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0.01"}, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(rate_limited))
    with pytest.raises(RateLimited):
        await post_json(client, "http://x/", headers={}, payload={}, timeout_s=1, provider="p")
    await client.aclose()

    def server_error(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.AsyncClient(transport=httpx.MockTransport(server_error))
    with pytest.raises(ProviderError):
        await post_json(client, "http://x/", headers={}, payload={}, timeout_s=1, provider="p")
    await client.aclose()

    def timeout(_req: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    with pytest.raises(ProviderTimeout):
        await post_json(client, "http://x/", headers={}, payload={}, timeout_s=1, provider="p")
    await client.aclose()


@pytest.mark.asyncio
async def test_post_json_non_object_body() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        await post_json(client, "http://x/", headers={}, payload={}, timeout_s=1, provider="p")
    await client.aclose()


@pytest.mark.asyncio
async def test_local_probe_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A down local server reports 'unreachable', not a crash."""
    from clean_evals.connectivity import probe_provider

    monkeypatch.setenv("CLEAN_EVALS_LOCAL_BASE_URL", "http://127.0.0.1:1/v1")

    def boom(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    probe = await probe_provider("local", client=client)
    await client.aclose()
    assert probe.status == "unreachable"
