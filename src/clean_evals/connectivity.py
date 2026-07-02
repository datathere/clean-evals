"""Live provider connectivity and model discovery.

"Connected" in the UI means verified: an authenticated request to the
provider succeeded. The same request returns the provider's model list,
which the catalog merges with the pricing table — new snapshots appear
without a package update.

Results are cached in-process for a few minutes, keyed by the key itself,
so page loads do not hammer provider APIs and a changed key re-verifies
at once.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from clean_evals.pricing import PROVIDER_ENV_VARS

_log = logging.getLogger(__name__)

ProviderStatus = Literal["connected", "invalid_key", "unreachable", "not_configured"]

_VERIFY_TIMEOUT_S = 5.0
_CACHE_TTL_S = 300.0

_ANTHROPIC_VERSION = "2023-06-01"

# OpenAI's /v1/models mixes chat models with embeddings, audio, and image
# models; keep chat completions only.
_OPENAI_INCLUDE = re.compile(r"^(gpt-|o\d)")
_OPENAI_EXCLUDE = re.compile(
    r"embedding|whisper|tts|dall-e|audio|realtime|moderation|transcribe|search|image|instruct"
)


@dataclass(frozen=True, slots=True)
class ProviderProbe:
    """Result of one provider check: status plus the models it reports."""

    status: ProviderStatus
    models: tuple[str, ...] = field(default=())


def _endpoints(api_key: str) -> dict[str, tuple[str, dict[str, str]]]:
    return {
        "anthropic": (
            "https://api.anthropic.com/v1/models?limit=100",
            {"x-api-key": api_key, "anthropic-version": _ANTHROPIC_VERSION},
        ),
        "openai": (
            "https://api.openai.com/v1/models",
            {"authorization": f"Bearer {api_key}"},
        ),
        "google": (
            "https://generativelanguage.googleapis.com/v1beta/models",
            {"x-goog-api-key": api_key},
        ),
        "openrouter": (
            "https://openrouter.ai/api/v1/key",
            {"authorization": f"Bearer {api_key}"},
        ),
    }


def _parse_models(provider: str, body: Any) -> tuple[str, ...]:
    """Chat-capable, dated model ids from a provider's list response."""
    if not isinstance(body, dict):
        return ()
    ids: list[str] = []
    if provider == "anthropic":
        ids = [m.get("id", "") for m in body.get("data", []) if isinstance(m, dict)]
    elif provider == "openai":
        ids = [
            mid
            for m in body.get("data", [])
            if isinstance(m, dict)
            and _OPENAI_INCLUDE.match(mid := m.get("id", ""))
            and not _OPENAI_EXCLUDE.search(mid)
        ]
    elif provider == "google":
        for m in body.get("models", []):
            if not isinstance(m, dict):
                continue
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            ids.append(str(m.get("name", "")).removeprefix("models/"))
    # Floating aliases are rejected by RunConfig; do not offer them.
    return tuple(sorted(i for i in ids if i and not i.endswith("-latest")))


_cache: dict[str, tuple[float, ProviderProbe]] = {}
_cache_lock = asyncio.Lock()


def _cache_key(provider: str, api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    return f"{provider}:{digest}"


async def probe_provider(
    provider: str,
    *,
    client: httpx.AsyncClient,
) -> ProviderProbe:
    """One provider's live status and model list. Cached per key."""
    env_var = PROVIDER_ENV_VARS.get(provider, "")
    api_key = os.environ.get(env_var, "").strip()
    if not api_key:
        return ProviderProbe("not_configured")

    key = _cache_key(provider, api_key)
    async with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < _CACHE_TTL_S:
            return hit[1]

    endpoint = _endpoints(api_key).get(provider)
    if endpoint is None:
        return ProviderProbe("not_configured")
    url, headers = endpoint

    probe: ProviderProbe
    try:
        resp = await client.get(url, headers=headers, timeout=_VERIFY_TIMEOUT_S)
        if resp.status_code < 300:
            try:
                models = _parse_models(provider, resp.json())
            except ValueError:
                models = ()
            probe = ProviderProbe("connected", models)
        elif resp.status_code in (401, 403):
            probe = ProviderProbe("invalid_key")
        else:
            _log.warning("probe %s: unexpected HTTP %s", provider, resp.status_code)
            probe = ProviderProbe("unreachable")
    except httpx.HTTPError as exc:
        _log.warning("probe %s: %r", provider, exc)
        probe = ProviderProbe("unreachable")

    async with _cache_lock:
        _cache[key] = (time.monotonic(), probe)
    return probe


async def probe_all(providers: list[str]) -> dict[str, ProviderProbe]:
    """Probe the given providers concurrently."""
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(probe_provider(p, client=client) for p in providers))
    return dict(zip(providers, results, strict=True))
