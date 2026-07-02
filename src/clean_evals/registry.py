"""Discover and instantiate plugins.

Three registries: :class:`AdapterRegistry`, :class:`ScorerRegistry`,
:class:`ReporterRegistry`. Each loads built-ins eagerly and lazily resolves
external plugins via :mod:`importlib.metadata` entry points.

Entry-point groups:

- ``clean_evals.adapters``
- ``clean_evals.scorers``
- ``clean_evals.reporters``

Example (third-party plugin in your ``pyproject.toml``):

.. code-block:: toml

    [project.entry-points."clean_evals.scorers"]
    levenshtein = "my_pkg.scorers:LevenshteinScorer"

The registries are populated lazily on first ``get`` / ``names`` call so that
``import clean_evals`` itself stays fast.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import threading
from typing import Any, Generic, TypeVar, cast

from clean_evals.errors import UnknownPlugin
from clean_evals.protocols import ModelAdapter, Reporter, Scorer

T = TypeVar("T")

_log = logging.getLogger(__name__)


class _BaseRegistry(Generic[T]):
    """Shared registry mechanics. Not part of the public API."""

    entry_point_group: str
    kind: str

    def __init__(self) -> None:
        self._items: dict[str, type[T]] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def register(self, name: str, cls: type[T]) -> None:
        """Register an in-process plugin under ``name``.

        Most users don't call this directly — entry points handle external
        plugins, and built-ins are baked in. Use it in tests or to wire a
        plugin defined in the same process without packaging metadata.
        """
        with self._lock:
            if name in self._items and self._items[name] is not cls:
                _log.warning(
                    "Overwriting %s %r: %s -> %s",
                    self.kind,
                    name,
                    self._items[name].__name__,
                    cls.__name__,
                )
            self._items[name] = cls

    def names(self) -> list[str]:
        """Return all registered plugin names, sorted."""
        self._ensure_loaded()
        return sorted(self._items.keys())

    def get(self, name: str) -> type[T]:
        """Return the plugin class registered under ``name``.

        Raises:
            UnknownPlugin: When ``name`` has not been registered.
        """
        self._ensure_loaded()
        try:
            return self._items[name]
        except KeyError as exc:
            raise UnknownPlugin(
                f"No {self.kind} registered as {name!r}. "
                f"Available: {', '.join(sorted(self._items)) or '(none)'}"
            ) from exc

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            # Re-check under the lock: another thread may have loaded while
            # we waited. mypy can't see cross-thread mutation, hence the loop
            # shape instead of a second early return.
            if not self._loaded:
                self._load_builtins()
                self._load_entry_points()
                self._loaded = True

    def _load_builtins(self) -> None:
        """Subclasses populate from in-tree built-ins."""

    def _load_entry_points(self) -> None:
        eps = importlib.metadata.entry_points(group=self.entry_point_group)
        for ep in eps:
            try:
                obj = ep.load()
            except Exception as exc:
                _log.warning(
                    "Failed to load %s entry point %r from %r: %s",
                    self.kind,
                    ep.name,
                    ep.value,
                    exc,
                )
                continue
            if not isinstance(obj, type):
                _log.warning(
                    "Entry point %r resolved to non-class %r; skipping",
                    ep.name,
                    obj,
                )
                continue
            self._items.setdefault(ep.name, cast(type[T], obj))


class AdapterRegistry(_BaseRegistry[ModelAdapter]):
    entry_point_group = "clean_evals.adapters"
    kind = "adapter"

    def _load_builtins(self) -> None:
        for module_path, attr in (
            ("clean_evals.adapters.anthropic", "AnthropicAdapter"),
            ("clean_evals.adapters.openai", "OpenAIAdapter"),
            ("clean_evals.adapters.google", "GoogleAdapter"),
            ("clean_evals.adapters.openrouter", "OpenRouterAdapter"),
        ):
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, attr)
            except Exception as exc:
                _log.warning("Built-in adapter %s.%s missing: %s", module_path, attr, exc)
                continue
            self._items.setdefault(cls.provider, cls)


class ScorerRegistry(_BaseRegistry[Scorer]):
    entry_point_group = "clean_evals.scorers"
    kind = "scorer"

    def _load_builtins(self) -> None:
        for module_path, attr in (
            ("clean_evals.scorers.exact_match", "ExactMatchScorer"),
            ("clean_evals.scorers.json_field_match", "JsonFieldMatchScorer"),
            ("clean_evals.scorers.llm_judge", "LLMJudgeScorer"),
        ):
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, attr)
            except Exception as exc:
                _log.warning("Built-in scorer %s.%s missing: %s", module_path, attr, exc)
                continue
            self._items.setdefault(cls.name, cls)

    def build(self, name: str, config: dict[str, Any]) -> Scorer:
        """Instantiate a scorer by name with config dict."""
        cls = self.get(name)
        return cls.from_config(config)


class ReporterRegistry(_BaseRegistry[Reporter]):
    entry_point_group = "clean_evals.reporters"
    kind = "reporter"

    def _load_builtins(self) -> None:
        for module_path, attr in (
            ("clean_evals.reporters.markdown", "MarkdownReporter"),
            ("clean_evals.reporters.jsonl", "JSONLReporter"),
            ("clean_evals.reporters.junit", "JUnitReporter"),
            ("clean_evals.reporters.console", "ConsoleReporter"),
        ):
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, attr)
            except Exception as exc:
                _log.warning("Built-in reporter %s.%s missing: %s", module_path, attr, exc)
                continue
            self._items.setdefault(cls.name, cls)


# Module-level singletons. Tests can construct fresh instances.
adapters = AdapterRegistry()
scorers = ScorerRegistry()
reporters = ReporterRegistry()
