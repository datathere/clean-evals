"""Pydantic shapes returned by the REST API.

Separate from the domain models so we can shape the API output for the UI
without leaking ORM details. The frontend's TypeScript types mirror these.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class DatasetOut(_Out):
    id: int
    name: str
    version: str
    description: str | None
    scorer: str
    case_count: int
    locked_count: int = 0
    has_runs: bool = False
    scorer_config: dict[str, Any] = Field(default_factory=dict)
    request_shape: Literal["raw", "templated", "chat"] = "raw"
    system_prompt: str | None = None
    shared_context: str | None = None
    user_template: str | None = None
    locked_at: datetime | None
    created_at: datetime


class CaseOut(_Out):
    id: int
    case_id_external: str
    input: dict[str, Any]
    expected: dict[str, Any] | None
    tags: list[str]
    locked: bool
    rev: int


class RunSummaryRow(_Out):
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


class RunOut(_Out):
    id: str
    dataset: str
    dataset_id: int
    dataset_version: str
    config: dict[str, Any]
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    summary: dict[str, RunSummaryRow]
    artifact_uri: str | None
    pricing_version: str
    triggered_by: str
    created_at: datetime


class CaseResultOut(_Out):
    case_id: str
    model: str
    status: str
    score: float | None
    passed: bool | None
    latency_ms: int | None
    cost_usd: float | None
    error: str | None
    started_at: datetime
    finished_at: datetime
    # Joined from the golden dataset + stored response so the UI can show
    # expected-vs-got without a second round trip.
    input: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    response: dict[str, Any] | None = None


class RecommendationOut(_Out):
    kind: Literal["max_accuracy", "price_performance", "lowest_cost"]
    model: str | None
    rationale: str
    summary: RunSummaryRow | None


class CostProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    calls_per_month: int = Field(ge=1)
    score_floor: float = Field(ge=0.0, le=1.0, default=0.0)


class CostProjectionRow(_Out):
    model: str
    score_mean: float
    qualifies: bool
    projected_monthly_usd: float


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: int
    cron: str
    enabled: bool = True
    config: dict[str, Any]


class ScheduleOut(_Out):
    id: int
    dataset_id: int
    cron: str
    enabled: bool
    config: dict[str, Any]
    last_run_at: datetime | None
    next_run_at: datetime | None


class CaseEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected: dict[str, Any] | None
    rev: int  # optimistic-concurrency token


# ---------------------------------------------------------------------------
# Golden path (docs/docs/flow.md): prompt spec, candidates, review, judge
# ---------------------------------------------------------------------------


class DatasetSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_prompt: str | None = None
    shared_context: str | None = None
    user_template: str | None = None
    scorer_config: dict[str, Any] | None = None


class PromptSpecIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_shape: Literal["raw", "templated", "chat"]
    system_prompt: str | None = None
    shared_context: str | None = None
    user_template: str | None = None


class RequestPreviewOut(_Out):
    case_id_external: str
    system: str | None
    user: str
    # Chat-shaped datasets replay prior turns before `user`; the preview
    # must show the request actually sent, history included.
    history: list[dict[str, str]] | None = None


class ModelParamsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: list[str] = Field(min_length=1)
    max_cost_usd: float = Field(default=5.0, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    model_params: dict[str, ModelParamsIn] = Field(default_factory=dict)


class GenerationStatusOut(_Out):
    status: str  # idle|running|done|error|aborted_cost
    total: int = 0
    done: int = 0
    errors: int = 0
    cost_usd: float = 0.0
    detail: str | None = None
    candidate_count: int = 0


class CandidateOut(_Out):
    id: int
    case_id: int
    case_id_external: str
    model: str
    content: str
    parsed: dict[str, Any] | None
    status: str
    error: str | None
    latency_ms: int | None
    cost_usd: float | None
    rating: int | None
    feedback: str | None


class RatingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=5)
    feedback: str | None = None


class GoldenPickIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: int | None = None
    expected: dict[str, Any] | None = None
    lock: bool = True


class ModelPickOut(_Out):
    model: str
    tier: str
    reason: str


class SuggestionOut(_Out):
    picks: list[ModelPickOut]
    picked_by: str | None


class CalibrateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judge_model: str


class JudgeConfigOut(_Out):
    id: int
    dataset_id: int
    version: int
    judge_model: str
    agreement: dict[str, Any]
    created_at: datetime


class ModelCapabilitiesOut(_Out):
    supports_temperature: bool
    supports_seed: bool
    reasoning_efforts: list[str]
    supports_max_output_tokens: bool


class CatalogModelOut(_Out):
    id: str
    input_per_mtok: float | None
    output_per_mtok: float | None
    overridden: bool = False
    listed: bool = False  # reported by the provider's model API just now
    excluded: bool = False
    description: str | None = None
    context_length: int | None = None
    capabilities: ModelCapabilitiesOut


class ExclusionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    excluded: bool


class PricingOverrideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    input_per_mtok: float = Field(gt=0)
    output_per_mtok: float = Field(gt=0)


class PricingApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PricingOverrideIn] = Field(min_length=1)


class PriceProposalOut(_Out):
    provider: str
    model: str
    current_input: float | None
    current_output: float | None
    new_input: float
    new_output: float
    source: str


class ProviderOut(_Out):
    provider: str
    env_var: str
    # "connected" means a live authenticated request to the provider
    # succeeded — not merely that the env var is set.
    status: Literal["connected", "invalid_key", "unreachable", "not_configured"]
    connected: bool
    models: list[CatalogModelOut]


class TriggerRunOut(_Out):
    mode: Literal["inline", "queue"]
    task_id: str | None = None  # queue mode: Celery task id


class InlineRunStatusOut(_Out):
    status: str  # idle|running|done|error
    run_id: str | None = None
    detail: str | None = None


class TriggerRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: int
    config: dict[str, Any]
    mode: Literal["inline", "queue"] = "inline"


# ---------------------------------------------------------------------------
# Telemetry: ingest, inbox, promotion, monitoring
# ---------------------------------------------------------------------------


class TelemetryRejectionOut(_Out):
    index: int
    error: str


class TelemetryIngestOut(_Out):
    accepted: int
    duplicates: list[str]
    rejected: list[TelemetryRejectionOut]
    scrubber: str | None  # entry-point name, or null = envelopes stored raw


class TelemetryExchangeOut(_Out):
    id: int
    interaction_id: str
    source: str
    dataset: str
    kind: str
    occurred_at: datetime
    outcome: str | None
    turn_index: int
    context: list[dict[str, str]]
    request_text: str
    request_input: dict[str, Any] | None
    response_text: str
    response_parsed: dict[str, Any] | None
    response_model: str
    alternatives: list[dict[str, Any]]
    regen_count: int
    label: str | None
    verdict: str | None
    rating: int | None
    feedback: str | None
    proposed_expected: dict[str, Any] | None
    judge_score: float | None
    status: str
    promoted_case_id: int | None
    auto_locked: bool
    spot_check: bool
    spot_check_resolved: str | None


class TelemetryInboxOut(_Out):
    total: int
    exchanges: list[TelemetryExchangeOut]


class TelemetryPromoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lock: bool = False
    expected: dict[str, Any] | None = None


class TelemetryPromoteOut(_Out):
    case_id: int
    dataset_id: int


class SpotCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Literal["confirmed", "overturned"]


class TelemetryDeriveOut(_Out):
    interactions: int
    exchanges: int
    auto_locked: int
    classifier_cost_usd: float
    skipped_budget: int
    errors: int


class TelemetrySeriesRow(_Out):
    date: str
    source: str
    model: str
    exchanges: int
    positive: int
    negative: int
    incomplete: int
    unrated: int
    acceptance_rate: float
    correction_rate: float
    mean_rating: float | None
    mean_regens: float
    judge_scored: int
    mean_judge_score: float | None


class TelemetrySourceRow(_Out):
    source: str
    interactions: int
    accept_rate: float
    mean_turns_to_accept: float | None


class TelemetryStatsOut(_Out):
    days: int
    series: list[TelemetrySeriesRow]
    sources: list[TelemetrySourceRow]


class AutolockStateOut(_Out):
    enabled: bool
    checked: int
    overturned: int
    overturn_rate: float
    disable_threshold: float
    self_disabled: bool
