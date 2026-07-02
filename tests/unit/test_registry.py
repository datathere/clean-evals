"""Plugin registry tests."""

from __future__ import annotations

import pytest

from clean_evals.errors import UnknownPlugin
from clean_evals.registry import (
    AdapterRegistry,
    ReporterRegistry,
    ScorerRegistry,
    adapters,
    reporters,
    scorers,
)


def test_builtins_present() -> None:
    assert "exact_match" in scorers.names()
    assert "json_field_match" in scorers.names()
    assert "llm_judge" in scorers.names()
    assert "anthropic" in adapters.names()
    assert "openai" in adapters.names()
    assert "google" in adapters.names()
    assert "openrouter" in adapters.names()
    assert {"markdown", "jsonl", "junit", "console"}.issubset(reporters.names())


def test_unknown_plugin_raises() -> None:
    fresh = ScorerRegistry()
    with pytest.raises(UnknownPlugin):
        fresh.get("nonexistent")


def test_register_adds_in_process() -> None:
    fresh = AdapterRegistry()

    class Dummy:
        provider = "dummy"

    fresh.register("dummy", Dummy)
    assert fresh.get("dummy") is Dummy


def test_reporter_registry_isolated() -> None:
    fresh = ReporterRegistry()
    assert "markdown" in fresh.names()


def test_scorer_build_invokes_from_config() -> None:
    s = scorers.build("exact_match", {"field": "label"})
    assert s.name == "exact_match"
