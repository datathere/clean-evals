"""Model metadata from OpenRouter's public catalog.

OpenRouter's ``/api/v1/models`` is the one machine-readable source with
per-model definitions: description, context length, and the parameters a
model accepts (``supported_parameters``). Anthropic and OpenAI return
bare ids from their own APIs.

The catalog uses this to enrich models it can map to a direct provider:
descriptions and context lengths in the UI, and data-driven capabilities
instead of hand rules. Models absent from OpenRouter fall back to the
rules in :mod:`clean_evals.capabilities`. Fetched without a key, cached
in-process, and a failed fetch degrades to the fallback — never an error.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from clean_evals.capabilities import REASONING_EFFORTS, ModelCapabilities

_log = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

_FETCH_TIMEOUT_S = 10.0
_CACHE_TTL_S = 600.0

_PREFIXES = {"openai/": "openai", "anthropic/": "anthropic", "google/": "google"}

# Providers list dated snapshots ("claude-sonnet-4-5-20250929",
# "gpt-4o-2024-08-06"); OpenRouter names the undated model with dots
# ("claude-sonnet-4.5"). Both normalise to the same key.
_DATE_SUFFIX = re.compile(r"-(\d{8}|\d{4}-\d{2}-\d{2})$")

# Adapters that send a reasoning effort level to the provider.
_EFFORT_PROVIDERS = frozenset({"openai", "openrouter"})


def _norm(model: str) -> str:
    return _DATE_SUFFIX.sub("", model.replace(".", "-"))


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Definitions OpenRouter publishes for a model."""

    description: str | None
    context_length: int | None
    supported_parameters: tuple[str, ...]

    def capabilities(self, provider: str) -> ModelCapabilities | None:
        """Capabilities derived from ``supported_parameters``, if published.

        A knob is offered only when the model accepts it AND the provider's
        adapter can send it — the Anthropic and Google APIs expose reasoning
        through parameters our adapters do not map to an effort level.
        """
        if not self.supported_parameters:
            return None
        params = set(self.supported_parameters)
        offers_effort = "reasoning" in params and provider in _EFFORT_PROVIDERS
        return ModelCapabilities(
            supports_temperature="temperature" in params,
            supports_seed="seed" in params,
            reasoning_efforts=REASONING_EFFORTS if offers_effort else (),
            supports_max_output_tokens="max_tokens" in params,
        )


def parse_metadata(body: dict[str, Any]) -> dict[tuple[str, str], ModelMetadata]:
    """Table keyed by (provider, normalised model id).

    When a dated snapshot and the undated model normalise to the same key,
    the undated entry wins — it is the model page, not a variant.
    """
    table: dict[tuple[str, str], ModelMetadata] = {}
    exact: set[tuple[str, str]] = set()
    for entry in body.get("data", []):
        if not isinstance(entry, dict):
            continue
        full_id = str(entry.get("id", ""))
        for prefix, provider in _PREFIXES.items():
            if full_id.startswith(prefix):
                model = full_id.removeprefix(prefix)
                key = (provider, _norm(model))
                is_exact = _norm(model) == model.replace(".", "-")
                if key in table and key in exact and not is_exact:
                    break
                description = entry.get("description")
                context_length = entry.get("context_length")
                params = entry.get("supported_parameters")
                table[key] = ModelMetadata(
                    description=str(description) if description else None,
                    context_length=int(context_length) if context_length else None,
                    supported_parameters=(
                        tuple(str(p) for p in params) if isinstance(params, list) else ()
                    ),
                )
                if is_exact:
                    exact.add(key)
                break
    return table


def lookup(
    table: dict[tuple[str, str], ModelMetadata], provider: str, model: str
) -> ModelMetadata | None:
    """Metadata for a model id as a direct provider reports it."""
    return table.get((provider, _norm(model)))


_cache: tuple[float, dict[tuple[str, str], ModelMetadata]] | None = None
_cache_lock = asyncio.Lock()


async def model_metadata() -> dict[tuple[str, str], ModelMetadata]:
    """The metadata table, cached. Empty when OpenRouter is unreachable."""
    global _cache
    async with _cache_lock:
        if _cache is not None and time.monotonic() - _cache[0] < _CACHE_TTL_S:
            return _cache[1]
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(OPENROUTER_MODELS_URL, timeout=_FETCH_TIMEOUT_S)
            resp.raise_for_status()
            table = parse_metadata(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        _log.warning("model metadata fetch failed: %r", exc)
        return _cache[1] if _cache is not None else {}
    async with _cache_lock:
        _cache = (time.monotonic(), table)
    return table
