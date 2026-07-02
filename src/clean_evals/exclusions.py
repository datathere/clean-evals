"""Excluded models.

Providers list dozens of models; most teams use a handful. Excluded
models are hidden from the model pickers and skipped by the price
refresh. They stay visible on the Models page, where the exclusion can
be lifted.

Stored in ``clean-evals-data/excluded-models.yml`` so exclusions survive
re-verification, price refreshes, and restarts:

.. code-block:: yaml

    openai:
      - gpt-3.5-turbo-0125
      - gpt-4-turbo-2024-04-09
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import yaml

_log = logging.getLogger(__name__)

_EXCLUDED_ENV = "CLEAN_EVALS_EXCLUDED_MODELS_FILE"
_DEFAULT_PATH = Path("./clean-evals-data/excluded-models.yml")

_lock = threading.Lock()
_cache: tuple[float, frozenset[tuple[str, str]]] | None = None


def _path() -> Path:
    env = os.environ.get(_EXCLUDED_ENV, "").strip()
    return Path(env) if env else _DEFAULT_PATH


def excluded_models() -> frozenset[tuple[str, str]]:
    """(provider, model) pairs currently excluded."""
    global _cache
    path = _path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return frozenset()
    with _lock:
        if _cache is not None and _cache[0] == mtime:
            return _cache[1]
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            _log.warning("excluded-models file unreadable (%s); ignoring", exc)
            return frozenset()
        pairs = frozenset(
            (str(provider), str(model))
            for provider, models in raw.items()
            if isinstance(models, list)
            for model in models
        )
        _cache = (mtime, pairs)
        return pairs


def _write(pairs: frozenset[tuple[str, str]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[str]] = {}
    for provider, model in sorted(pairs):
        data.setdefault(provider, []).append(model)
    path.write_text(
        "# clean-evals excluded models. Hidden from pickers; editable on the Models page.\n"
        + yaml.safe_dump(data, sort_keys=True),
        encoding="utf-8",
    )
    with _lock:
        global _cache
        _cache = None


def set_excluded(provider: str, model: str, excluded: bool) -> None:
    """Exclude or include one model and persist the file."""
    pairs = set(excluded_models())
    if excluded:
        pairs.add((provider, model))
    else:
        pairs.discard((provider, model))
    _write(frozenset(pairs))
