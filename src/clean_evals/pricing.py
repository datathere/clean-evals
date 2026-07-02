"""Provider pricing: a built-in table plus local overrides.

Costs are stored as USD per 1M tokens. Runs stamp the pricing version they
were costed under, so historical comparisons remain valid after price
changes.

Two layers:

- ``_TABLE`` — the built-in table, updated with releases.
- ``clean-evals-data/pricing.yml`` — local overrides, edited from the
  Models page or by hand. Overrides win on conflict and may add models
  the built-in table does not know. When overrides are present, the
  effective version carries a content hash (``2026.04+ab12cd34``).

Override file format:

.. code-block:: yaml

    anthropic:
      claude-haiku-4-5-20251001: {input: 0.80, output: 4.00}
    openai:
      a-new-model: {input: 1.00, output: 2.00}
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

_log = logging.getLogger(__name__)

PRICING_VERSION = "2026.04"
"""Bump this every time ``_TABLE`` changes."""


@dataclass(frozen=True, slots=True)
class Price:
    """Per-1M-token pricing for a (provider, model) pair.

    Attributes:
        input_per_mtok: USD charged per 1,000,000 input (prompt) tokens.
        output_per_mtok: USD charged per 1,000,000 output (completion) tokens.
    """

    input_per_mtok: float
    output_per_mtok: float


# (provider, model) -> Price
# Numbers below were the listed list-prices at the start of 2026 Q2.
# Real production deployments should override via a pricing file once
# clean-evals-pricing exists; until then bump PRICING_VERSION on edits.
_TABLE: dict[tuple[str, str], Price] = {
    # Anthropic
    ("anthropic", "claude-opus-4-7"): Price(15.00, 75.00),
    ("anthropic", "claude-sonnet-4-6"): Price(3.00, 15.00),
    ("anthropic", "claude-haiku-4-5-20251001"): Price(0.80, 4.00),
    ("anthropic", "claude-3-5-sonnet-20241022"): Price(3.00, 15.00),
    ("anthropic", "claude-3-5-haiku-20241022"): Price(0.80, 4.00),
    ("anthropic", "claude-3-opus-20240229"): Price(15.00, 75.00),
    # OpenAI
    ("openai", "gpt-4o-2024-11-20"): Price(2.50, 10.00),
    ("openai", "gpt-4o-2024-08-06"): Price(2.50, 10.00),
    ("openai", "gpt-4o-mini-2024-07-18"): Price(0.15, 0.60),
    ("openai", "gpt-4-turbo-2024-04-09"): Price(10.00, 30.00),
    ("openai", "o1-2024-12-17"): Price(15.00, 60.00),
    ("openai", "o1-mini-2024-09-12"): Price(3.00, 12.00),
    # Google
    ("google", "gemini-1.5-pro-002"): Price(1.25, 5.00),
    ("google", "gemini-1.5-flash-002"): Price(0.075, 0.30),
    ("google", "gemini-2.0-flash-001"): Price(0.10, 0.40),
    # OpenRouter is a proxy; pricing varies per upstream model. clean-evals
    # treats OpenRouter as a fall-through: when an OpenRouter call returns
    # cost in its response, we trust that. Otherwise zero (with a note).
}


_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
    ("gemini-", "google"),
    # OpenAI-compatible local endpoints (Ollama, LM Studio, vLLM, ...).
    ("local/", "local"),
)

# OpenAI's reasoning series (o1, o3, o4-mini, ...) shares no usable string
# prefix; matched by pattern, mirroring capabilities._OPENAI_REASONING.
_OPENAI_O_SERIES = re.compile(r"^o\d")

# Which environment variable connects each provider. Used by the model
# catalog endpoint so the UI can show real availability, and by docs.
# The local provider is configured by a base URL rather than a key.
PROVIDER_ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "local": "CLEAN_EVALS_LOCAL_BASE_URL",
}


def infer_provider(model: str) -> str:
    """Best-effort guess of the provider for a model id.

    Used by the runner's leaderboard rendering and the pricing lookup when the
    caller doesn't supply a provider explicitly. Adapters always supply their
    own provider; this fallback is for CLI ergonomics only.

    Raises:
        ValueError: When the model id doesn't match any known prefix.
    """
    for prefix, provider in _PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return provider
    if _OPENAI_O_SERIES.match(model):
        return "openai"
    raise ValueError(
        f"Cannot infer provider for model {model!r}. "
        "Pass an explicit adapter or extend pricing._PROVIDER_PREFIXES."
    )


# ---------------------------------------------------------------------------
# Local overrides
# ---------------------------------------------------------------------------

_OVERRIDE_ENV = "CLEAN_EVALS_PRICING_FILE"
_DEFAULT_OVERRIDE_PATH = Path("./clean-evals-data/pricing.yml")

_override_lock = threading.Lock()
_override_cache: tuple[float, dict[tuple[str, str], Price]] | None = None


def override_path() -> Path:
    env = os.environ.get(_OVERRIDE_ENV, "").strip()
    return Path(env) if env else _DEFAULT_OVERRIDE_PATH


def overrides() -> dict[tuple[str, str], Price]:
    """The local override table. Reloaded when the file changes."""
    global _override_cache
    path = override_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _override_lock:
        if _override_cache is not None and _override_cache[0] == mtime:
            return _override_cache[1]
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            _log.warning("pricing overrides unreadable (%s); ignoring", exc)
            return {}
        table: dict[tuple[str, str], Price] = {}
        for provider, models in raw.items():
            if not isinstance(models, dict):
                continue
            for model, price in models.items():
                try:
                    table[(str(provider), str(model))] = Price(
                        input_per_mtok=float(price["input"]),
                        output_per_mtok=float(price["output"]),
                    )
                except (KeyError, TypeError, ValueError):
                    _log.warning("pricing override %s/%s malformed; skipped", provider, model)
        _override_cache = (mtime, table)
        return table


def _write_overrides(table: dict[tuple[str, str], Price]) -> None:
    path = override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, dict[str, dict[str, float]]] = {}
    for (provider, model), price in sorted(table.items()):
        data.setdefault(provider, {})[model] = {
            "input": price.input_per_mtok,
            "output": price.output_per_mtok,
        }
    path.write_text(
        "# clean-evals pricing overrides (USD per 1M tokens).\n"
        "# Overrides win over the built-in table. Editable from the Models page.\n"
        + yaml.safe_dump(data, sort_keys=True),
        encoding="utf-8",
    )
    with _override_lock:
        global _override_cache
        _override_cache = None


def set_override(
    provider: str, model: str, *, input_per_mtok: float, output_per_mtok: float
) -> None:
    """Add or update one override and persist the file."""
    table = dict(overrides())
    table[(provider, model)] = Price(input_per_mtok, output_per_mtok)
    _write_overrides(table)


def set_overrides(entries: dict[tuple[str, str], Price]) -> None:
    """Add or update several overrides in one write."""
    table = dict(overrides())
    table.update(entries)
    _write_overrides(table)


def remove_override(provider: str, model: str) -> bool:
    """Remove one override. Returns False when it was not set."""
    table = dict(overrides())
    if (provider, model) not in table:
        return False
    del table[(provider, model)]
    _write_overrides(table)
    return True


def effective_version() -> str:
    """``PRICING_VERSION``, extended with a content hash when overrides exist."""
    table = overrides()
    if not table:
        return PRICING_VERSION
    canonical = json.dumps(
        {
            f"{p}/{m}": [pr.input_per_mtok, pr.output_per_mtok]
            for (p, m), pr in sorted(table.items())
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:8]
    return f"{PRICING_VERSION}+{digest}"


def lookup(provider: str, model: str) -> Price | None:
    """Return the price for a model, or ``None`` if unknown.

    Local overrides win over the built-in table. Returning ``None`` rather
    than raising lets the runner record an uncosted call instead of
    crashing a long-running eval over a missing pricing entry.
    """
    return overrides().get((provider, model)) or _TABLE.get((provider, model))


def compute_cost(
    provider: str,
    model: str,
    *,
    tokens_in: int,
    tokens_out: int,
) -> float:
    """Compute the USD cost for a single call.

    Returns ``0.0`` and is silent when the price is unknown — adapters that
    receive an authoritative cost from the provider response should bypass
    this and use that value instead.
    """
    price = lookup(provider, model)
    if price is None:
        return 0.0
    return (
        max(tokens_in, 0) * price.input_per_mtok / 1_000_000
        + max(tokens_out, 0) * price.output_per_mtok / 1_000_000
    )


def known_models() -> list[tuple[str, str]]:
    """(provider, model) pairs from the built-in table and overrides.

    Sorted, stable. Useful for ``clean-evals list-models`` and tests.
    """
    return sorted(set(_TABLE) | set(overrides()))
