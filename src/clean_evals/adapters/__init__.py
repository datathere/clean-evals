"""Built-in model adapters.

Each adapter is registered via the ``clean_evals.adapters`` entry-point group
in ``pyproject.toml``. They can also be addressed directly:

>>> from clean_evals.adapters.anthropic import AnthropicAdapter

External adapters are first-class — there is nothing special about being
in-tree. Drop a ``clean_evals.adapters`` entry point in your package and
you appear in the registry alongside these.
"""

from __future__ import annotations

from clean_evals.adapters.anthropic import AnthropicAdapter
from clean_evals.adapters.google import GoogleAdapter
from clean_evals.adapters.local import LocalAdapter
from clean_evals.adapters.openai import OpenAIAdapter
from clean_evals.adapters.openrouter import OpenRouterAdapter

__all__ = [
    "AnthropicAdapter",
    "GoogleAdapter",
    "LocalAdapter",
    "OpenAIAdapter",
    "OpenRouterAdapter",
]
