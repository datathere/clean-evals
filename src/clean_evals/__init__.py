"""clean-evals — measure AI quality across models.

Public API. Anything not exported here lives in ``clean_evals._internal`` and
may change without notice.

Example:
    >>> import asyncio
    >>> from clean_evals import Dataset, Runner, RunConfig
    >>> ds = Dataset.from_yaml("examples/sentiment/dataset.yml")
    >>> runner = Runner()
    >>> result = runner.run_sync(
    ...     ds,
    ...     RunConfig(
    ...         models=["claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"],
    ...         max_cost_usd=1.0,
    ...     ),
    ... )
"""

from __future__ import annotations

from clean_evals._internal.version import __version__
from clean_evals.models import (
    Case,
    CaseResult,
    Dataset,
    ModelResponse,
    ModelSummary,
    RunConfig,
    RunResult,
    ScoreResult,
)
from clean_evals.protocols import (
    ModelAdapter,
    Reporter,
    Scorer,
    Scrubber,
)
from clean_evals.runner import Runner

__all__ = [
    "Case",
    "CaseResult",
    "Dataset",
    "ModelAdapter",
    "ModelResponse",
    "ModelSummary",
    "Reporter",
    "RunConfig",
    "RunResult",
    "Runner",
    "ScoreResult",
    "Scorer",
    "Scrubber",
    "__version__",
]
