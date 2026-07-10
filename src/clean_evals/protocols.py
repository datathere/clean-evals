"""Plugin extension protocols.

Three extension points: ``Scorer``, ``ModelAdapter``, ``Reporter``. Two
scrubbing protocols guard data boundaries: ``Scrubber`` at the dataset
loader, ``TelemetryScrubber`` at telemetry ingest.

All are runtime-checkable :class:`typing.Protocol` types — implementations
do not need to inherit. Registration happens via Python entry points, see
``pyproject.toml`` ``[project.entry-points."clean_evals.*"]`` blocks.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from clean_evals.models import (
        Case,
        ModelResponse,
        RunResult,
        ScoreResult,
    )
    from clean_evals.prompting import ChatMessage
    from clean_evals.telemetry import StructuredInteraction, TranscriptInteraction


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
        history: Sequence[ChatMessage] | None = None,
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


@runtime_checkable
class TelemetryScrubber(Protocol):
    """Optional plugin for cleaning PII from telemetry envelopes at ingest.

    Selected via ``CLEAN_EVALS_TELEMETRY_SCRUBBER`` naming an entry point in
    the ``clean_evals.telemetry_scrubbers`` group; called once per envelope
    *before* anything is persisted. Telemetry is production data by
    definition — when no scrubber is configured, envelopes are stored raw,
    and the docs and Telemetry inbox say so plainly.

    Implementations must be pure — same input, same output.
    """

    def scrub_interaction(
        self, interaction: StructuredInteraction | TranscriptInteraction
    ) -> StructuredInteraction | TranscriptInteraction: ...
