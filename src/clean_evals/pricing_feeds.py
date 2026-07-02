"""Machine-readable pricing feeds.

Two sources, no HTML scraping:

- LiteLLM's community-maintained pricing JSON on GitHub. Primary source;
  updated within days of provider price changes.
- OpenRouter's public model API. Fills gaps for models LiteLLM lacks.

Feeds propose price updates; nothing changes until the user applies them
into the local overrides (see :mod:`clean_evals.pricing`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from clean_evals.pricing import Price, lookup

_log = logging.getLogger(__name__)

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/" "model_prices_and_context_window.json"
)
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

_FETCH_TIMEOUT_S = 10.0

# litellm_provider -> clean-evals provider
_LITELLM_PROVIDERS = {"openai": "openai", "anthropic": "anthropic", "gemini": "google"}
# OpenRouter id prefix -> clean-evals provider
_OPENROUTER_PREFIXES = {"openai/": "openai", "anthropic/": "anthropic", "google/": "google"}


@dataclass(frozen=True, slots=True)
class PriceProposal:
    """One suggested price change, current -> proposed."""

    provider: str
    model: str
    current_input: float | None
    current_output: float | None
    new_input: float
    new_output: float
    source: str


def _parse_litellm(body: dict[str, Any]) -> dict[tuple[str, str], Price]:
    table: dict[tuple[str, str], Price] = {}
    for key, entry in body.items():
        if not isinstance(entry, dict):
            continue
        provider = _LITELLM_PROVIDERS.get(str(entry.get("litellm_provider", "")))
        if provider is None:
            continue
        model = key.split("/", 1)[1] if "/" in key else key
        try:
            input_cost = float(entry["input_cost_per_token"])
            output_cost = float(entry["output_cost_per_token"])
        except (KeyError, TypeError, ValueError):
            continue
        if input_cost <= 0 or output_cost <= 0:
            continue
        table[(provider, model)] = Price(
            input_per_mtok=round(input_cost * 1_000_000, 6),
            output_per_mtok=round(output_cost * 1_000_000, 6),
        )
    return table


def _parse_openrouter(body: dict[str, Any]) -> dict[tuple[str, str], Price]:
    table: dict[tuple[str, str], Price] = {}
    for entry in body.get("data", []):
        if not isinstance(entry, dict):
            continue
        full_id = str(entry.get("id", ""))
        provider = None
        for prefix, mapped in _OPENROUTER_PREFIXES.items():
            if full_id.startswith(prefix):
                provider = mapped
                model = full_id.removeprefix(prefix)
                break
        if provider is None:
            continue
        pricing = entry.get("pricing") or {}
        try:
            input_cost = float(pricing["prompt"])
            output_cost = float(pricing["completion"])
        except (KeyError, TypeError, ValueError):
            continue
        if input_cost <= 0 or output_cost <= 0:
            continue
        table[(provider, model)] = Price(
            input_per_mtok=round(input_cost * 1_000_000, 6),
            output_per_mtok=round(output_cost * 1_000_000, 6),
        )
    return table


async def fetch_feed_prices() -> dict[tuple[str, str], Price]:
    """Merged feed prices. LiteLLM wins; OpenRouter fills gaps.

    Raises:
        httpx.HTTPError: When neither feed is reachable.
    """
    merged: dict[tuple[str, str], Price] = {}
    errors: list[httpx.HTTPError] = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(OPENROUTER_MODELS_URL, timeout=_FETCH_TIMEOUT_S)
            resp.raise_for_status()
            merged.update(_parse_openrouter(resp.json()))
        except httpx.HTTPError as exc:
            _log.warning("openrouter feed failed: %s", exc)
            errors.append(exc)
        try:
            resp = await client.get(LITELLM_URL, timeout=_FETCH_TIMEOUT_S)
            resp.raise_for_status()
            merged.update(_parse_litellm(resp.json()))
        except httpx.HTTPError as exc:
            _log.warning("litellm feed failed: %s", exc)
            errors.append(exc)
    if not merged and errors:
        raise errors[-1]
    return merged


def build_proposals(
    catalog_models: list[tuple[str, str]],
    feed: dict[tuple[str, str], Price],
) -> list[PriceProposal]:
    """Price changes for models in the catalog, current vs feed."""
    proposals: list[PriceProposal] = []
    for provider, model in catalog_models:
        feed_price = feed.get((provider, model))
        if feed_price is None:
            continue
        current = lookup(provider, model)
        if current is not None and _close(current, feed_price):
            continue
        proposals.append(
            PriceProposal(
                provider=provider,
                model=model,
                current_input=current.input_per_mtok if current else None,
                current_output=current.output_per_mtok if current else None,
                new_input=feed_price.input_per_mtok,
                new_output=feed_price.output_per_mtok,
                source="litellm/openrouter",
            )
        )
    return sorted(proposals, key=lambda p: (p.provider, p.model))


def _close(a: Price, b: Price) -> bool:
    def near(x: float, y: float) -> bool:
        return abs(x - y) <= max(x, y) * 0.005

    return near(a.input_per_mtok, b.input_per_mtok) and near(a.output_per_mtok, b.output_per_mtok)
