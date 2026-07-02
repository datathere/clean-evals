"""Tests for the pricing module."""

from __future__ import annotations

import pytest

from clean_evals.pricing import (
    PRICING_VERSION,
    compute_cost,
    infer_provider,
    known_models,
    lookup,
)


def test_pricing_version_present() -> None:
    assert PRICING_VERSION
    assert isinstance(PRICING_VERSION, str)


def test_known_models_sorted() -> None:
    pairs = known_models()
    assert pairs == sorted(pairs)
    assert ("anthropic", "claude-3-5-sonnet-20241022") in pairs


def test_lookup_returns_none_for_unknown() -> None:
    assert lookup("anthropic", "fake-model") is None
    p = lookup("openai", "gpt-4o-mini-2024-07-18")
    assert p is not None
    assert p.input_per_mtok > 0


def test_compute_cost_zero_for_unknown() -> None:
    assert compute_cost("anthropic", "fake-model", tokens_in=10, tokens_out=10) == 0.0


def test_compute_cost_correct_for_known() -> None:
    cost = compute_cost(
        "openai", "gpt-4o-mini-2024-07-18", tokens_in=1_000_000, tokens_out=1_000_000
    )
    p = lookup("openai", "gpt-4o-mini-2024-07-18")
    assert p is not None
    assert pytest.approx(cost, rel=1e-9) == p.input_per_mtok + p.output_per_mtok


def test_infer_provider_known_prefixes() -> None:
    assert infer_provider("claude-3-5-sonnet-20241022") == "anthropic"
    assert infer_provider("gpt-4o-2024-11-20") == "openai"
    assert infer_provider("o1-2024-12-17") == "openai"
    assert infer_provider("gemini-1.5-pro-002") == "google"
    assert infer_provider("local/llama3.2") == "local"
    assert infer_provider("local/qwen2.5-coder:14b") == "local"
    # The whole o-series routes to OpenAI, matching capabilities' pattern.
    assert infer_provider("o3") == "openai"
    assert infer_provider("o3-mini-2025-01-31") == "openai"
    assert infer_provider("o4-mini") == "openai"


def test_infer_provider_unknown() -> None:
    with pytest.raises(ValueError):
        infer_provider("unknown-model")
