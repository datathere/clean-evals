"""Public data models.

Every public boundary of clean-evals exchanges Pydantic models defined here.
All models forbid extra fields (``extra="forbid"``); unknown keys are errors,
not warnings. Result-bearing models are ``frozen=True`` — they describe a
moment in time and must not be mutated downstream.

These types are part of the stable public API. Field additions ratchet a
minor version; field removals or renames ratchet a major.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from clean_evals.protocols import Scrubber


_RUN_STATUS = Literal["ok", "error", "timeout", "schema_invalid", "aborted_cost"]
_DATASET_VERSION_RE = re.compile(r"^v?[0-9]+(?:\.[0-9]+){0,2}(?:[-+][0-9A-Za-z.\-]+)?$")
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-:]+$")


class _StrictModel(BaseModel):
    """Base for every public model. Forbids unknown keys."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _FrozenStrictModel(BaseModel):
    """Frozen variant for result-bearing types."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Case(_FrozenStrictModel):
    """A single eval input + optional expected output.

    Attributes:
        id: Stable identifier within the dataset. Allowed characters: alphanumerics,
            underscore, dash, dot, colon. No spaces.
        input: Free-form structured input passed to the prompt template.
        expected: Expected output for the case. ``None`` while the case is being
            built in the Dataset Builder; required once the dataset is locked.
        tags: Free-form tags used for filtering and per-tag accuracy breakdowns.
        metadata: Free-form metadata. Not used by the runner; passed through to
            reporters.
        locked: When ``True``, ``expected`` is immutable. The Dataset Builder
            sets this on save; editing a locked case must bump the dataset
            version.

    Example:
        >>> Case(id="case_001", input={"text": "I love it"}, expected={"label": "positive"})
        Case(id='case_001', ...)
    """

    id: str
    input: dict[str, Any]
    expected: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    locked: bool = False

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v:
            raise ValueError("Case.id may not be empty")
        if not _CASE_ID_RE.match(v):
            raise ValueError(
                f"Case.id {v!r} contains illegal characters; allowed: A-Z, a-z, 0-9, _ - . :"
            )
        return v


class Dataset(_StrictModel):
    """A versioned collection of ``Case`` rows plus its scoring configuration.

    Datasets are immutable once tagged: once ``locked_at`` is set on the
    backing storage row, the version is sealed and any edit must produce a new
    version. Historical runs against ``v1`` remain comparable after ``v2`` ships.

    The ``scorer`` field names a scorer registered under the
    ``clean_evals.scorers`` entry-point group. ``scorer_config`` is passed
    verbatim to ``Scorer.from_config``.

    Loading from YAML:
        >>> Dataset.from_yaml("examples/sentiment/dataset.yml")  # doctest: +SKIP
    """

    name: str
    version: str
    description: str | None = None
    cases: list[Case]
    scorer: str
    scorer_config: dict[str, Any] = Field(default_factory=dict)
    # Prompt spec (docs/docs/flow.md, stage 1). "raw" sends each case
    # verbatim; "templated" assembles system prompt + context + variables;
    # "chat" replays each case's prior turns as message history.
    request_shape: Literal["raw", "templated", "chat"] = "raw"
    system_prompt: str | None = None
    shared_context: str | None = None
    user_template: str | None = None

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not _DATASET_VERSION_RE.match(v):
            raise ValueError(
                f"Dataset.version {v!r} must match SemVer-like pattern (e.g. 'v1', '1.2', '0.3.0')"
            )
        return v

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v:
            raise ValueError("Dataset.name may not be empty")
        return v

    @model_validator(mode="after")
    def _validate_unique_case_ids(self) -> Dataset:
        seen: set[str] = set()
        for case in self.cases:
            if case.id in seen:
                raise ValueError(f"Duplicate case id within dataset: {case.id!r}")
            seen.add(case.id)
        return self

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        scrubber: Scrubber | None = None,
    ) -> Dataset:
        """Load a dataset from a YAML file.

        The YAML may inline cases, or reference a sidecar JSONL via
        ``cases_jsonl: ./path/to/cases.jsonl`` relative to the YAML.

        Args:
            path: Path to the YAML file.
            scrubber: Optional ``Scrubber`` plugin run on every case after
                load. Useful for redacting PII before the case crosses any
                boundary.

        Returns:
            A validated ``Dataset``.
        """
        p = Path(path)
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ValueError(f"{p}: top-level must be a mapping")

        cases_jsonl = raw.pop("cases_jsonl", None)
        if cases_jsonl is not None:
            import json as _json

            jsonl_path = (p.parent / cases_jsonl).resolve()
            cases: list[dict[str, Any]] = []
            with jsonl_path.open("r", encoding="utf-8") as fh:
                for lineno, raw_line in enumerate(fh, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        cases.append(_json.loads(line))
                    except _json.JSONDecodeError as e:
                        raise ValueError(f"{jsonl_path}:{lineno}: invalid JSON ({e.msg})") from e
            raw["cases"] = cases

        ds = cls.model_validate(raw)
        if scrubber is not None:
            ds = ds.model_copy(update={"cases": [scrubber.scrub(c) for c in ds.cases]})
        return ds

    def to_yaml(self, path: str | Path) -> None:
        """Write the dataset to a YAML file.

        Cases are inlined. For large datasets, write JSONL separately and
        reference it from the YAML — but that's a workflow you do by hand.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        with p.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


class ModelResponse(_FrozenStrictModel):
    """A single model invocation's output and accounting.

    Attributes:
        content: Raw response text.
        parsed: ``content`` parsed as JSON when ``response_format="json"`` was
            requested. ``None`` otherwise, or when parsing failed (the runner
            then records ``status="schema_invalid"`` on the case result).
        tokens_in: Input tokens reported by the provider. ``-1`` when the
            provider does not return a count.
        tokens_out: Output tokens reported by the provider. ``-1`` when the
            provider does not return a count.
        latency_ms: Wall-clock latency including network. Adapter-measured.
        cost_usd: Computed via ``pricing.py`` at the time of the run.
        raw: Provider response as a dict, for debugging and per-case diff.
    """

    content: str
    parsed: dict[str, Any] | None = None
    tokens_in: int = -1
    tokens_out: int = -1
    latency_ms: int
    cost_usd: float
    raw: dict[str, Any] = Field(default_factory=dict)


class ScoreResult(_FrozenStrictModel):
    """Output of a single scorer invocation.

    Attributes:
        score: Normalised 0.0–1.0 score. Required.
        passed: Whether this counts as a "pass" for leaderboard purposes.
            Scorers decide their own threshold; ``passed`` is reported alongside
            ``score`` so the runner can compute pass-rate without re-thresholding.
        breakdown: Optional sub-component scores for richer reporting
            (e.g. ``{"name_match": 1.0, "type_match": 0.5}``).
        notes: Optional free-form text — handy for LLM-judge rationales.
    """

    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    breakdown: dict[str, float] = Field(default_factory=dict)
    notes: str | None = None


class CaseResult(_FrozenStrictModel):
    """One ``(case, model)`` outcome.

    A model erroring (timeout, 5xx, content filter, schema-invalid output)
    produces a ``CaseResult`` with the appropriate ``status`` rather than
    crashing the run. Reports distinguish wrong answers from infrastructure
    errors so a model that 500s on 30% of cases is not "70% accurate."

    Attributes:
        case_id: Foreign key to ``Case.id``.
        model: Snapshot model id (e.g. ``"gpt-4o-2024-11-20"``).
        status: ``"ok"`` for a scored response; ``"error"``, ``"timeout"``,
            ``"schema_invalid"``, or ``"aborted_cost"`` for failure modes.
        response: The model's response, or ``None`` if the call did not
            complete.
        score: Scorer output, or ``None`` if scoring was skipped (e.g. for an
            errored case).
        error: Captured error payload when ``status != "ok"``.
        started_at, finished_at: UTC timestamps with microsecond precision.
    """

    case_id: str
    model: str
    status: _RUN_STATUS
    response: ModelResponse | None = None
    score: ScoreResult | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime


class ModelParams(_StrictModel):
    """Per-model request parameters, set when the model supports them.

    Attributes:
        temperature: Overrides ``RunConfig.temperature`` for this model.
        reasoning_effort: Effort level for reasoning models (low, medium,
            high).
        max_output_tokens: Output token cap for this model's calls.
    """

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)


class RunConfig(_StrictModel):
    """Configuration for a single eval run.

    Attributes:
        models: Snapshot model ids only — floating aliases ending in
            ``-latest`` are rejected to keep historical runs comparable.
        model_params: Per-model parameters keyed by model id (see
            :class:`ModelParams`). Missing keys fall back to the run-level
            settings.
        concurrency: Optional per-provider concurrency caps. Empty = uncapped
            (the runner backs off on 429 anyway).
        timeout_s: Per-call timeout, in seconds. Adapter-enforced.
        retries: Retries on transient failures (429, 5xx, network errors).
        seed: Provider seed for determinism. ``None`` opts out.
        temperature: Sampling temperature. ``> 0`` makes runs non-deterministic;
            the report carries a header warning when this is the case.
        max_cost_usd: Best-effort ceiling for the run. Spend is checked as
            results arrive; cases that have not started when the ceiling
            trips are aborted with ``status="aborted_cost"``, but calls
            already in flight complete, so actual spend can overshoot the
            ceiling (bounded by concurrency). Verify real spend in the
            provider's billing console.
    """

    models: list[str]
    model_params: dict[str, ModelParams] = Field(default_factory=dict)
    concurrency: dict[str, int] = Field(default_factory=dict)
    timeout_s: float = 120.0
    retries: int = 2
    seed: int | None = 42
    temperature: float = 0.0
    max_cost_usd: float = 5.0

    @field_validator("models")
    @classmethod
    def _validate_models(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("RunConfig.models must contain at least one model")
        for m in v:
            # local/ models are pinned by the file on disk; the dated-snapshot
            # rule exists for hosted providers whose aliases move.
            if m.startswith("local/"):
                continue
            if m.endswith("-latest") or m == "latest":
                raise ValueError(
                    f"Floating alias {m!r} rejected. clean-evals requires dated snapshot ids."
                )
        return v

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, v: float) -> float:
        if v < 0.0 or v > 2.0:
            raise ValueError("RunConfig.temperature must be in [0.0, 2.0]")
        return v

    @field_validator("max_cost_usd")
    @classmethod
    def _validate_max_cost(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("RunConfig.max_cost_usd must be > 0")
        return v


class ModelSummary(_FrozenStrictModel):
    """Per-model leaderboard row in a ``RunResult``.

    Attributes:
        cost_per_correct_usd: Cost per passed case. ``None`` when zero cases
            passed (avoids division-by-zero presented as "infinity good").
        pricing_version: The frozen pricing table version used for cost
            attribution. Rerunning under newer pricing creates a new run; old
            summaries still report the spend that was actually charged.
    """

    model: str
    cases_run: int
    cases_passed: int
    score_mean: float
    score_p50: float
    latency_p95_ms: int
    error_rate: float
    total_cost_usd: float
    cost_per_correct_usd: float | None
    pricing_version: str


class RunResult(_StrictModel):
    """Top-level result for a single ``Runner.run`` invocation.

    Reporters consume this. Storage persists this. The Decision UI renders
    this. It is the unit of comparison.
    """

    run_id: str
    dataset: str
    dataset_version: str
    config: RunConfig
    cases: list[CaseResult]
    summary: dict[str, ModelSummary]
    started_at: datetime
    finished_at: datetime
    pricing_version: str
    deterministic: bool
    notes: list[str] = Field(default_factory=list)
