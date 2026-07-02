"""Plugin extension protocols.

Three extension points: ``Scorer``, ``ModelAdapter``, ``Reporter``. A fourth,
``Scrubber``, is used at the dataset-loader boundary.

All four are runtime-checkable :class:`typing.Protocol` types — implementations
do not need to inherit. Registration happens via Python entry points, see
``pyproject.toml`` ``[project.entry-points."clean_evals.*"]`` blocks.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from clean_evals.models import (
        Case,
        ModelResponse,
        RunResult,
        ScoreResult,
    )


@runtime_checkable
class Scorer(Protocol):
    """Computes a 0.0–1.0 quality score for a model's output.

    Implementations should be pure: same ``(case, response)`` always yields
    the same ``ScoreResult``. Anything stochastic (LLM judges) should be
    seeded so the run is reproducible.

    Class attributes:
        name: The registry key under which this scorer is discoverable.
            Datasets reference it via ``Dataset.scorer``.
    """

    name: ClassVar[str]

    def score(self, case: Case, response: ModelResponse) -> ScoreResult: ...

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Scorer: ...


@runtime_checkable
class ModelAdapter(Protocol):
    """Talks to a single model provider.

    Adapters MUST:

    - Be ``async``-native (use ``httpx.AsyncClient``, never ``requests``).
    - Validate that the requested ``model`` is a dated snapshot. Floating
      aliases like ``-latest`` are rejected at ``RunConfig`` validation, but
      adapters should also defend in depth.
    - Return ``ModelResponse.cost_usd`` populated via ``clean_evals.pricing``
      using the prompt's actual token counts.
    - On HTTP 429, raise ``RateLimited`` with the ``Retry-After`` value if
      present so the runner can back off.
    - On other transient failures, raise the standard exception types from
      :mod:`clean_evals.errors` so the runner can retry consistently.
    """

    provider: ClassVar[str]

    async def complete(
        self,
        prompt: str,
        model: str,
        *,
        temperature: float,
        seed: int | None,
        timeout_s: float,
        response_format: Literal["text", "json"] = "text",
        system: str | None = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelResponse: ...


@runtime_checkable
class Reporter(Protocol):
    """Writes a ``RunResult`` to a destination.

    Reporters are invoked synchronously after the run completes. Each
    reporter MAY write multiple files; ``write`` returns the path of the
    primary artifact (the one humans/CI typically open first).
    """

    name: ClassVar[str]

    def write(self, result: RunResult, output_dir: Path) -> Path: ...


@runtime_checkable
class Scrubber(Protocol):
    """Optional plugin for cleaning PII / sensitive data during dataset load.

    Called by ``Dataset.from_yaml(..., scrubber=...)`` once per case after
    parsing. Implementations must be pure — same input, same output.
    """

    def scrub(self, case: Case) -> Case: ...
