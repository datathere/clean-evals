"""Per-model request parameters.

Providers do not expose parameter schemas through their APIs, so this is
rule-based: provider defaults plus model-family exceptions. The catalog
returns these with the model list, and the UI asks for the matching
parameters when a model is picked.

Rules encoded here:

- OpenAI reasoning models (``o1``, ``o3``, ..., and the ``gpt-5`` family)
  reject ``temperature`` and accept ``reasoning_effort`` (low, medium,
  high).
- Anthropic deprecated ``temperature`` starting with the Opus 4.7
  generation; the adapter also retries without it when a model the
  rules do not know rejects it.
- OpenAI supports ``seed``; Anthropic and Google do not.
- ``max_output_tokens`` is accepted by the four providers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_OPENAI_REASONING = re.compile(r"^(o\d|gpt-5)")
_ANTHROPIC_NO_TEMPERATURE = re.compile(r"^claude-(opus-4-[7-9]|fable|mythos|[a-z]+-5)")

REASONING_EFFORTS = ("low", "medium", "high")


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """Which request parameters a model accepts."""

    supports_temperature: bool = True
    supports_seed: bool = False
    reasoning_efforts: tuple[str, ...] = field(default=())
    supports_max_output_tokens: bool = True


def capabilities(provider: str, model: str) -> ModelCapabilities:
    """Capabilities for one (provider, model) pair."""
    if provider == "openai":
        if _OPENAI_REASONING.match(model):
            return ModelCapabilities(
                supports_temperature=False,
                supports_seed=True,
                reasoning_efforts=REASONING_EFFORTS,
            )
        return ModelCapabilities(supports_seed=True)
    if provider == "openrouter":
        return ModelCapabilities(supports_seed=True, reasoning_efforts=REASONING_EFFORTS)
    if provider == "local":
        # OpenAI-compatible servers accept seed; servers that do not simply
        # ignore the parameter.
        return ModelCapabilities(supports_seed=True)
    if provider == "anthropic" and _ANTHROPIC_NO_TEMPERATURE.match(model):
        return ModelCapabilities(supports_temperature=False)
    # anthropic (older families), google: temperature and max tokens.
    return ModelCapabilities()
