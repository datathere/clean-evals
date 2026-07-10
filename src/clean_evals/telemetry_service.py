"""Telemetry persistence, derivation, promotion, and monitoring.

The pure logic lives in :mod:`clean_evals.telemetry`; this module owns the
side effects:

- **Ingest** — validate envelopes, apply the optional telemetry scrubber,
  and store them losslessly in ``telemetry_interactions``.
- **Derive** — turn pending interactions into ``telemetry_exchanges``.
  Structured interactions derive deterministically and free; transcripts
  need one LLM classifier call each, metered against a daily ceiling.
- **Promote** — turn a derived exchange into a case + candidate output +
  implicit rating in the target dataset, through the same lock flow the
  Builder uses.
- **Auto-lock** — the opt-in lane: an exchange whose explicit accept,
  implicit rating, and calibrated judge all concur is promoted and locked
  without a human, except for a spot-check sample that routes to review
  anyway. The lane disables itself when the human overturn rate on that
  sample crosses a threshold — no automated pathway runs without a
  measured error estimate.
- **Stats** — per-day aggregates for the monitoring page.

Environment:

- ``CLEAN_EVALS_TELEMETRY_CLASSIFIER_MODEL`` — transcript classifier model
  (default ``claude-haiku-4-5-20251001``).
- ``CLEAN_EVALS_TELEMETRY_DAILY_COST_LIMIT_USD`` — classifier spend ceiling
  per UTC day (default ``5.0``). Best-effort, like every cost limit here.
- ``CLEAN_EVALS_TELEMETRY_SCRUBBER`` — entry-point name in the
  ``clean_evals.telemetry_scrubbers`` group. Unset = envelopes stored raw.
- ``CLEAN_EVALS_TELEMETRY_AUTOLOCK`` — ``1`` enables the auto-lock lane.
- ``CLEAN_EVALS_TELEMETRY_AUTOLOCK_KAPPA`` — minimum judge-calibration
  kappa for the lane to operate (default ``0.6``).
- ``CLEAN_EVALS_TELEMETRY_SPOTCHECK_RATE`` — fraction of auto-locked
  exchanges routed to human spot-check anyway (default ``0.10``).
- ``CLEAN_EVALS_TELEMETRY_OVERTURN_DISABLE`` — overturn rate at which the
  lane self-disables, over at least 5 resolved spot checks (default
  ``0.2``).
- ``CLEAN_EVALS_TELEMETRY_JUDGE_SAMPLE_RATE`` — fraction of derived
  exchanges scored by the dataset's calibrated judge for monitoring
  (default ``0.0`` — off; judge sampling spends money).
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from clean_evals.models import Case, ModelResponse
from clean_evals.pricing import infer_provider
from clean_evals.protocols import ModelAdapter, TelemetryScrubber
from clean_evals.registry import adapters as adapter_registry
from clean_evals.storage.db import (
    CandidateOutputRow,
    CaseRow,
    DatasetRow,
    JudgeConfigRow,
    RatingRow,
    TelemetryExchangeRow,
    TelemetryInteractionRow,
)
from clean_evals.telemetry import (
    DerivedExchange as _DerivedExchange,
)
from clean_evals.telemetry import (
    StructuredInteraction,
    TelemetryInteraction,
    TranscriptInteraction,
    build_classifier_prompt,
    derive_structured,
    explode_transcript,
    finalize_transcript_exchanges,
    parse_classifier_labels,
)

_log = logging.getLogger(__name__)

_DEFAULT_CLASSIFIER = "claude-haiku-4-5-20251001"
_DEFAULT_DAILY_LIMIT_USD = 5.0
_MIN_SPOT_CHECKS_FOR_DISABLE = 5
_CASE_ID_ILLEGAL = re.compile(r"[^A-Za-z0-9_.\-:]")

_interaction_adapter: TypeAdapter[TelemetryInteraction] = TypeAdapter(TelemetryInteraction)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        _log.warning("%s=%r is not a number; using %s", name, raw, default)
        return default


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Scrubber
# ---------------------------------------------------------------------------


def load_scrubber() -> TelemetryScrubber | None:
    """Resolve the configured telemetry scrubber, or ``None``.

    Raises:
        ValueError: When ``CLEAN_EVALS_TELEMETRY_SCRUBBER`` names an entry
            point that does not exist or does not satisfy the protocol —
            a configured-but-broken scrubber must fail ingest loudly, not
            silently store raw data.
    """
    name = os.environ.get("CLEAN_EVALS_TELEMETRY_SCRUBBER", "").strip()
    if not name:
        return None
    eps = importlib.metadata.entry_points(group="clean_evals.telemetry_scrubbers")
    for ep in eps:
        if ep.name == name:
            obj = ep.load()
            instance = obj() if isinstance(obj, type) else obj
            if not isinstance(instance, TelemetryScrubber):
                raise ValueError(
                    f"telemetry scrubber {name!r} does not implement TelemetryScrubber"
                )
            return instance
    raise ValueError(
        f"CLEAN_EVALS_TELEMETRY_SCRUBBER={name!r} matches no entry point in "
        "the 'clean_evals.telemetry_scrubbers' group"
    )


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    """Per-batch outcome. Rejections carry the item index and the reason."""

    accepted: int = 0
    duplicates: list[str] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)


def ingest_items(session: Session, items: list[Any]) -> IngestResult:
    """Validate, scrub, and store a batch of envelope dicts.

    Invalid items are rejected individually — one malformed envelope never
    sinks the batch. Duplicate ``(source, interaction_id)`` pairs are
    reported and skipped, making retries of the same batch idempotent —
    including a concurrent retry of the same batch: each insert flushes
    inside a savepoint, so a duplicate that slips past the existence check
    (committed by the other request between our SELECT and our INSERT)
    rolls back that one item as a duplicate instead of 500ing the batch.
    """
    result = IngestResult()
    scrubber = load_scrubber()
    seen: set[tuple[str, str]] = set()  # duplicates within this batch

    for index, item in enumerate(items):
        try:
            interaction = _interaction_adapter.validate_python(item)
        except ValidationError as exc:
            result.rejected.append({"index": index, "error": _first_error(exc)})
            continue
        if scrubber is not None:
            interaction = scrubber.scrub_interaction(interaction)

        key = (interaction.source, interaction.interaction_id)
        existing = session.execute(
            select(TelemetryInteractionRow.id).where(
                TelemetryInteractionRow.source == interaction.source,
                TelemetryInteractionRow.interaction_id == interaction.interaction_id,
            )
        ).first()
        if key in seen or existing is not None:
            result.duplicates.append(interaction.interaction_id)
            continue
        seen.add(key)

        outcome: str | None = None
        if isinstance(interaction, TranscriptInteraction):
            outcome = interaction.outcome.type if interaction.outcome else None
        else:
            outcome = "accept" if any(e.type == "accept" for e in interaction.events) else None

        try:
            with session.begin_nested():
                session.add(
                    TelemetryInteractionRow(
                        interaction_id=interaction.interaction_id,
                        source=interaction.source,
                        dataset_name=interaction.dataset,
                        kind=interaction.kind,
                        model=interaction.model,
                        occurred_at=interaction.occurred_at,
                        outcome=outcome,
                        envelope_jsonb=interaction.model_dump(mode="json"),
                        status="pending",
                    )
                )
        except IntegrityError:
            result.duplicates.append(interaction.interaction_id)
            continue
        result.accepted += 1

    session.flush()
    return result


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(part) for part in err.get("loc", ()))
    return f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid"))


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


@dataclass
class DeriveStats:
    """Outcome of one derivation pass."""

    interactions: int = 0
    exchanges: int = 0
    auto_locked: int = 0
    classifier_cost_usd: float = 0.0
    skipped_budget: int = 0
    errors: int = 0


def classifier_spend_today(session: Session) -> float:
    """Classifier spend since UTC midnight, keyed on when the classifier ran.

    Keying on ``created_at`` (ingest time) would make spend on a backlog
    ingested before midnight invisible to today's ceiling — a stalled queue
    could re-spend the full daily budget every day.
    """
    now = datetime.now(UTC)
    midnight = datetime(now.year, now.month, now.day, tzinfo=UTC)
    rows = session.execute(
        select(TelemetryInteractionRow.classifier_cost_usd).where(
            TelemetryInteractionRow.classified_at >= midnight
        )
    ).all()
    return sum(r[0] or 0.0 for r in rows)


async def derive_pending(
    session_factory: sessionmaker[Session],
    *,
    adapters: dict[str, ModelAdapter] | None = None,
) -> DeriveStats:
    """Derive every pending interaction into exchanges.

    Structured interactions always derive (deterministic, free). Transcript
    interactions each cost one classifier call; when the daily ceiling is
    reached they stay ``pending`` with a detail note and are retried by the
    next pass. A classifier failure derives the transcript with no labels —
    exchanges come out ``unrated`` rather than invented.
    """
    stats = DeriveStats()
    with session_factory() as session:
        pending_ids = [
            row_id
            for (row_id,) in session.execute(
                select(TelemetryInteractionRow.id)
                .where(TelemetryInteractionRow.status == "pending")
                .order_by(TelemetryInteractionRow.id)
            ).all()
        ]
        spent_today = classifier_spend_today(session)

    limit = _env_float("CLEAN_EVALS_TELEMETRY_DAILY_COST_LIMIT_USD", _DEFAULT_DAILY_LIMIT_USD)
    adapter_cache: dict[str, ModelAdapter] = dict(adapters or {})
    owned: list[ModelAdapter] = []

    try:
        for pk in pending_ids:
            with session_factory() as session:
                row = session.get(TelemetryInteractionRow, pk)
                if row is None or row.status != "pending":
                    continue
                try:
                    interaction = _interaction_adapter.validate_python(row.envelope_jsonb)
                except ValidationError as exc:
                    row.status = "error"
                    row.detail = f"stored envelope no longer validates: {_first_error(exc)}"
                    session.commit()
                    stats.errors += 1
                    continue

                if isinstance(interaction, StructuredInteraction):
                    exchanges = [derive_structured(interaction)]
                    cost = 0.0
                else:
                    if spent_today + stats.classifier_cost_usd >= limit:
                        row.detail = f"classifier daily ceiling ${limit:.2f} reached; will retry"
                        session.commit()
                        stats.skipped_budget += 1
                        continue
                    try:
                        exchanges, cost = await _derive_transcript(
                            interaction, adapter_cache, owned
                        )
                    except Exception as exc:
                        _log.warning(
                            "classifier failed for interaction %s: %s", row.interaction_id, exc
                        )
                        pending = explode_transcript(interaction)
                        exchanges = finalize_transcript_exchanges(interaction, pending, {})
                        cost = 0.0
                        row.detail = f"classifier failed; derived unrated: {exc}"
                    row.classified_at = datetime.now(UTC)

                row.classifier_cost_usd = cost
                stats.classifier_cost_usd += cost
                # Replace any unpromoted exchanges from a concurrent or
                # earlier pass in the same transaction: derivation is
                # idempotent per interaction, so a race between the
                # post-ingest background pass and a manual derive can
                # double-spend on the classifier but never persist
                # duplicate exchanges. Promoted ones are never touched.
                session.execute(
                    delete(TelemetryExchangeRow).where(
                        TelemetryExchangeRow.interaction_pk == row.id,
                        TelemetryExchangeRow.status == "derived",
                    )
                )
                exchange_pks: list[int] = []
                for ex in exchanges:
                    ex_row = _exchange_to_row(row.id, ex)
                    session.add(ex_row)
                    session.flush()
                    exchange_pks.append(ex_row.id)
                row.status = "derived"
                session.commit()
                stats.interactions += 1
                stats.exchanges += len(exchanges)

            stats.auto_locked += await _post_derive(session_factory, exchange_pks)
    finally:
        for adapter in owned:
            closer = getattr(adapter, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception as exc:
                    _log.warning("closing telemetry adapter raised %r; ignoring", exc)

    return stats


def _exchange_to_row(interaction_pk: int, ex: _DerivedExchange) -> TelemetryExchangeRow:
    return TelemetryExchangeRow(
        interaction_pk=interaction_pk,
        turn_index=ex.turn_index,
        input_hash=ex.input_hash,
        context_jsonb={"turns": ex.context},
        request_text=ex.request_text,
        request_input_jsonb=ex.request_input,
        response_text=ex.response_text,
        response_parsed_jsonb=ex.response_parsed,
        response_model=ex.response_model,
        alternatives_jsonb={"items": [alt.model_dump(mode="json") for alt in ex.alternatives]},
        regen_count=ex.regen_count,
        label=ex.label,
        verdict=ex.verdict,
        rating=ex.rating,
        feedback=ex.feedback,
        proposed_expected_jsonb=ex.proposed_expected,
        status="derived",
    )


async def _derive_transcript(
    interaction: TranscriptInteraction,
    adapter_cache: dict[str, ModelAdapter],
    owned: list[ModelAdapter],
) -> tuple[list[_DerivedExchange], float]:
    """One classifier call labels every follow-up; labels map to verdicts."""
    pending = explode_transcript(interaction)
    prompt, to_label = build_classifier_prompt(interaction)
    if not to_label:
        return finalize_transcript_exchanges(interaction, pending, {}), 0.0

    model = (
        os.environ.get("CLEAN_EVALS_TELEMETRY_CLASSIFIER_MODEL", "").strip() or _DEFAULT_CLASSIFIER
    )
    adapter = _adapter_for(model, adapter_cache, owned)
    response = await adapter.complete(
        prompt=prompt,
        model=model,
        temperature=0.0,
        seed=0,
        timeout_s=60.0,
        response_format="json",
    )
    labels = parse_classifier_labels(response.parsed or {}, to_label)
    return finalize_transcript_exchanges(interaction, pending, labels), response.cost_usd


def _adapter_for(
    model: str, cache: dict[str, ModelAdapter], owned: list[ModelAdapter]
) -> ModelAdapter:
    provider = infer_provider(model)
    if provider not in cache:
        adapter = adapter_registry.get(provider)()
        cache[provider] = adapter
        owned.append(adapter)
    return cache[provider]


# ---------------------------------------------------------------------------
# Judge sampling + auto-lock (post-derivation)
# ---------------------------------------------------------------------------


async def _post_derive(
    session_factory: sessionmaker[Session],
    exchange_pks: list[int],
) -> int:
    """Judge-sample and auto-lock freshly derived exchanges. Returns locks."""
    sample_rate = _env_float("CLEAN_EVALS_TELEMETRY_JUDGE_SAMPLE_RATE", 0.0)
    autolock = _env_flag("CLEAN_EVALS_TELEMETRY_AUTOLOCK")
    locked = 0
    for pk in exchange_pks:
        if sample_rate > 0 and secrets.randbelow(10_000) < int(sample_rate * 10_000):
            try:
                await _judge_exchange(session_factory, pk)
            except Exception as exc:
                _log.warning("judge sampling for exchange %s failed: %s", pk, exc)
        if autolock:
            try:
                if await _maybe_autolock(session_factory, pk):
                    locked += 1
            except Exception as exc:
                _log.warning("auto-lock for exchange %s failed: %s", pk, exc)
    return locked


def _latest_dataset(session: Session, name: str) -> DatasetRow | None:
    return session.execute(
        select(DatasetRow).where(DatasetRow.name == name).order_by(DatasetRow.id.desc()).limit(1)
    ).scalar_one_or_none()


def _judge_for_dataset(session: Session, dataset: DatasetRow) -> tuple[Any, float] | None:
    """The dataset's calibrated judge scorer + its kappa, or ``None``."""
    if dataset.scorer != "llm_judge":
        return None
    config_row = session.execute(
        select(JudgeConfigRow)
        .where(JudgeConfigRow.dataset_id == dataset.id)
        .order_by(JudgeConfigRow.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if config_row is None:
        return None
    # Calibration stores agreement as {"summary": {..., "kappa"}, "rows": []}.
    agreement = config_row.agreement_jsonb or {}
    summary = agreement.get("summary")
    kappa = float((summary if isinstance(summary, dict) else agreement).get("kappa", 0.0))
    from clean_evals.registry import scorers as scorer_registry

    scorer = scorer_registry.build("llm_judge", dataset.scorer_config or {})
    return scorer, kappa


def _exchange_case_input(row: TelemetryExchangeRow) -> dict[str, Any]:
    """The ``Case.input`` a promoted exchange would carry.

    Transcript cases carry the production system prompt per case (chat
    assembly prefers it over the dataset-level prompt); structured cases
    rely on the dataset-level system prompt set at dataset creation.
    """
    if row.request_input_jsonb is not None:
        return dict(row.request_input_jsonb)
    turns = (row.context_jsonb or {}).get("turns", [])
    input_payload: dict[str, Any] = {"message": row.request_text}
    if turns:
        input_payload["context"] = turns
    system = (row.interaction.envelope_jsonb or {}).get("system")
    if isinstance(system, str) and system.strip():
        input_payload["system"] = system
    return input_payload


async def _judge_exchange(session_factory: sessionmaker[Session], exchange_pk: int) -> None:
    """Score one exchange with the dataset's calibrated judge (monitoring)."""
    with session_factory() as session:
        row = session.get(TelemetryExchangeRow, exchange_pk)
        if row is None:
            return
        dataset = _latest_dataset(session, row.interaction.dataset_name)
        if dataset is None:
            return
        judge = _judge_for_dataset(session, dataset)
        if judge is None:
            return
        scorer, _ = judge
        case = _judge_case(row)
        response = _exchange_response(row)
    score = await asyncio.to_thread(scorer.score, case, response)
    with session_factory() as session:
        fresh = session.get(TelemetryExchangeRow, exchange_pk)
        if fresh is not None:
            fresh.judge_score = score.score
            session.commit()


def _exchange_response(row: TelemetryExchangeRow) -> ModelResponse:
    return ModelResponse(
        content=row.response_text,
        parsed=row.response_parsed_jsonb,
        latency_ms=0,
        cost_usd=0.0,
    )


def _judge_case(row: TelemetryExchangeRow) -> Case:
    """The case the judge scores an exchange against — with NO expected.

    The proposed golden answer *is* the response for untouched accepts;
    handing it to the judge as ``expected`` would make the judge compare
    the response to a copy of itself and pass every time — a circular
    signal, not an independent one. Judging with no expected mirrors
    calibration: the calibrated rubric's few-shot examples carry the
    standard, and the score reflects quality against that standard.
    """
    return Case(id=f"telemetry-{row.id}", input=_exchange_case_input(row), expected=None)


def autolock_state(session: Session) -> dict[str, Any]:
    """The lane's current health: spot-check counts and self-disable status."""
    resolved = session.execute(
        select(TelemetryExchangeRow.spot_check_resolved).where(
            TelemetryExchangeRow.spot_check.is_(True),
            TelemetryExchangeRow.spot_check_resolved.is_not(None),
        )
    ).all()
    checked = len(resolved)
    overturned = sum(1 for (r,) in resolved if r == "overturned")
    rate = (overturned / checked) if checked else 0.0
    threshold = _env_float("CLEAN_EVALS_TELEMETRY_OVERTURN_DISABLE", 0.2)
    disabled = checked >= _MIN_SPOT_CHECKS_FOR_DISABLE and rate >= threshold
    return {
        "enabled": _env_flag("CLEAN_EVALS_TELEMETRY_AUTOLOCK"),
        "checked": checked,
        "overturned": overturned,
        "overturn_rate": rate,
        "disable_threshold": threshold,
        "self_disabled": disabled,
    }


async def _maybe_autolock(session_factory: sessionmaker[Session], exchange_pk: int) -> bool:
    """Auto-lock one exchange when every independent signal concurs.

    Conditions: an explicit accept (labels ``accepted`` /
    ``accepted_with_edits`` — a real commit action, not inferred approval),
    implicit rating ≥ 4, a proposed golden answer, a calibrated judge with
    kappa above the threshold that passes the response, and a healthy
    overturn rate on past spot checks.
    """
    with session_factory() as session:
        row = session.get(TelemetryExchangeRow, exchange_pk)
        if row is None or row.status != "derived":
            return False
        if row.label not in ("accepted", "accepted_with_edits"):
            return False
        if row.verdict != "positive" or (row.rating or 0) < 4:
            return False
        if row.proposed_expected_jsonb is None:
            return False
        state = autolock_state(session)
        if state["self_disabled"]:
            _log.warning(
                "auto-lock self-disabled: overturn rate %.0f%% over %d spot checks",
                state["overturn_rate"] * 100,
                state["checked"],
            )
            return False
        dataset = _latest_dataset(session, row.interaction.dataset_name)
        if dataset is None:
            return False
        judge = _judge_for_dataset(session, dataset)
        if judge is None:
            return False
        scorer, kappa = judge
        if kappa < _env_float("CLEAN_EVALS_TELEMETRY_AUTOLOCK_KAPPA", 0.6):
            return False
        case = _judge_case(row)
        response = _exchange_response(row)

    score = await asyncio.to_thread(scorer.score, case, response)
    if not score.passed:
        return False

    spot_rate = _env_float("CLEAN_EVALS_TELEMETRY_SPOTCHECK_RATE", 0.10)
    spot = secrets.randbelow(10_000) < int(spot_rate * 10_000)
    with session_factory() as session:
        fresh = session.get(TelemetryExchangeRow, exchange_pk)
        if fresh is None or fresh.status != "derived":
            return False
        fresh.judge_score = score.score
        try:
            promote_exchange(session, exchange_pk, lock=True)
        except ValueError as exc:
            _log.info("auto-lock promotion for exchange %s refused: %s", exchange_pk, exc)
            session.rollback()
            return False
        fresh.auto_locked = True
        fresh.spot_check = spot
        session.commit()
    return True


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


def promote_exchange(
    session: Session,
    exchange_pk: int,
    *,
    lock: bool = False,
    expected_override: dict[str, Any] | None = None,
) -> int:
    """Promote a derived exchange into its dataset. Returns the case pk.

    Creates the dataset (``v1``, ``llm_judge`` scorer, ``chat`` shape for
    transcripts) when no dataset of that name exists yet. The kept response
    becomes a candidate output; regeneration alternatives become additional
    candidates; the implicit rating (when present) attaches to the kept one
    with ``source="implicit"``.

    Raises:
        ValueError: Unknown exchange, exchange not in ``derived`` state, a
            promoted duplicate of the same (dataset, context, request), or
            ``lock=True`` without any golden answer to lock.
    """
    row = session.get(TelemetryExchangeRow, exchange_pk)
    if row is None:
        raise ValueError(f"exchange {exchange_pk} not found")
    if row.status != "derived":
        raise ValueError(f"exchange {exchange_pk} is {row.status}, not derived")

    interaction = row.interaction
    duplicate = session.execute(
        select(TelemetryExchangeRow.id)
        .join(
            TelemetryInteractionRow,
            TelemetryInteractionRow.id == TelemetryExchangeRow.interaction_pk,
        )
        .where(
            TelemetryExchangeRow.input_hash == row.input_hash,
            TelemetryExchangeRow.status == "promoted",
            TelemetryInteractionRow.dataset_name == interaction.dataset_name,
            TelemetryExchangeRow.id != row.id,
        )
        .limit(1)
    ).first()
    if duplicate is not None:
        raise ValueError("an identical (context, request) was already promoted to this dataset")

    expected = expected_override if expected_override is not None else row.proposed_expected_jsonb
    if lock and expected is None:
        raise ValueError("cannot lock without a golden answer; provide expected")

    dataset = _latest_dataset(session, interaction.dataset_name)
    if dataset is None:
        # Structured cases replay through the templated shape: the default
        # template renders a single-field input verbatim and carries the
        # production system prompt in the system role. The raw shape would
        # JSON-wrap the input and has no system slot — a different request
        # than production sent. The first promoted interaction's system
        # prompt becomes the dataset's; transcripts carry theirs per case.
        envelope_system = (interaction.envelope_jsonb or {}).get("request", {}).get("system")
        dataset = DatasetRow(
            name=interaction.dataset_name,
            version="v1",
            description=f"Created from telemetry source {interaction.source!r}.",
            scorer="llm_judge",
            scorer_config={},
            request_shape="chat" if interaction.kind == "transcript" else "templated",
            system_prompt=(
                envelope_system
                if isinstance(envelope_system, str) and envelope_system.strip()
                else None
            ),
        )
        session.add(dataset)
        session.flush()
    elif interaction.kind == "transcript" and dataset.request_shape != "chat":
        raise ValueError(
            f"dataset {interaction.dataset_name!r} has request_shape="
            f"{dataset.request_shape!r}; transcript exchanges replay conversation "
            "context and require a chat-shaped dataset"
        )
    elif interaction.kind == "structured" and dataset.request_shape == "chat":
        raise ValueError(
            f"dataset {interaction.dataset_name!r} is chat-shaped; a structured "
            "exchange has no conversation to replay there — promote it to a "
            "raw or templated dataset (use a different dataset name)"
        )

    case_id = _unique_case_id(session, dataset.id, _external_case_id(row, interaction))
    case = CaseRow(
        dataset_id=dataset.id,
        case_id_external=case_id,
        input_jsonb=_exchange_case_input(row),
        expected_jsonb=expected,
        tags_jsonb=["telemetry", interaction.source],
        locked=lock and expected is not None,
        metadata_jsonb={
            "telemetry_interaction_id": interaction.interaction_id,
            "telemetry_source": interaction.source,
            "telemetry_turn_index": row.turn_index,
        },
    )
    session.add(case)
    session.flush()

    kept = CandidateOutputRow(
        case_id=case.id,
        model=row.response_model,
        content=row.response_text,
        parsed_jsonb=row.response_parsed_jsonb,
        status="ok",
    )
    session.add(kept)
    session.flush()
    if row.rating is not None:
        session.add(
            RatingRow(
                candidate_output_id=kept.id,
                rating=row.rating,
                feedback=row.feedback,
                source="implicit",
            )
        )
    alternatives = (row.alternatives_jsonb or {}).get("items", [])
    for i, alt in enumerate(alternatives, start=1):
        session.add(
            CandidateOutputRow(
                case_id=case.id,
                model=f"{alt.get('model') or row.response_model}#regen{i}",
                content=str(alt.get("text", "")),
                parsed_jsonb=None,
                status="ok",
            )
        )

    row.status = "promoted"
    row.promoted_case_id = case.id
    session.flush()
    return case.id


def _external_case_id(row: TelemetryExchangeRow, interaction: TelemetryInteractionRow) -> str:
    base = _CASE_ID_ILLEGAL.sub("-", interaction.interaction_id)
    if interaction.kind == "transcript":
        return f"{base}:{row.turn_index}"
    return base


def _unique_case_id(session: Session, dataset_id: int, candidate: str) -> str:
    """Suffix the id until it is free within the dataset (cross-source clashes)."""
    existing = {
        ext
        for (ext,) in session.execute(
            select(CaseRow.case_id_external).where(CaseRow.dataset_id == dataset_id)
        ).all()
    }
    if candidate not in existing:
        return candidate
    n = 2
    while f"{candidate}-{n}" in existing:
        n += 1
    return f"{candidate}-{n}"


def discard_exchange(session: Session, exchange_pk: int) -> None:
    """Mark a derived exchange as reviewed-and-rejected."""
    row = session.get(TelemetryExchangeRow, exchange_pk)
    if row is None:
        raise ValueError(f"exchange {exchange_pk} not found")
    if row.status != "derived":
        raise ValueError(f"exchange {exchange_pk} is {row.status}, not derived")
    row.status = "discarded"
    session.flush()


def resolve_spot_check(session: Session, exchange_pk: int, *, overturn: bool) -> None:
    """Resolve a spot-checked auto-lock; overturning also unlocks the case.

    Every resolution feeds the lane's measured error rate — see
    :func:`autolock_state`.
    """
    row = session.get(TelemetryExchangeRow, exchange_pk)
    if row is None:
        raise ValueError(f"exchange {exchange_pk} not found")
    if not row.spot_check or row.spot_check_resolved is not None:
        raise ValueError(f"exchange {exchange_pk} has no open spot check")
    row.spot_check_resolved = "overturned" if overturn else "confirmed"
    if overturn and row.promoted_case_id is not None:
        case = session.get(CaseRow, row.promoted_case_id)
        if case is not None:
            case.locked = False
            case.rev = case.rev + 1
    session.flush()


# ---------------------------------------------------------------------------
# Monitoring stats
# ---------------------------------------------------------------------------


def telemetry_stats(session: Session, *, days: int = 30) -> dict[str, Any]:
    """Per-day aggregates for the monitoring page.

    Aggregation happens in Python: the volumes a self-hosted instance sees
    do not justify dialect-specific SQL date functions, and correctness of
    the mechanism beats query cleverness here.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = session.execute(
        select(TelemetryExchangeRow, TelemetryInteractionRow)
        .join(
            TelemetryInteractionRow,
            TelemetryInteractionRow.id == TelemetryExchangeRow.interaction_pk,
        )
        .where(TelemetryInteractionRow.occurred_at >= cutoff)
    ).all()

    daily: dict[tuple[str, str, str], dict[str, Any]] = {}
    per_interaction: dict[int, dict[str, Any]] = {}
    for ex, inter in rows:
        occurred = inter.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)
        key = (occurred.date().isoformat(), inter.source, ex.response_model)
        bucket = daily.setdefault(
            key,
            {
                "date": key[0],
                "source": key[1],
                "model": key[2],
                "exchanges": 0,
                "positive": 0,
                "negative": 0,
                "incomplete": 0,
                "unrated": 0,
                "rated": 0,
                "rating_sum": 0,
                "regen_sum": 0,
                "judge_scored": 0,
                "judge_sum": 0.0,
            },
        )
        bucket["exchanges"] += 1
        bucket[ex.verdict or "unrated"] += 1
        if ex.rating is not None:
            bucket["rated"] += 1
            bucket["rating_sum"] += ex.rating
        bucket["regen_sum"] += ex.regen_count
        if ex.judge_score is not None:
            bucket["judge_scored"] += 1
            bucket["judge_sum"] += ex.judge_score

        info = per_interaction.setdefault(
            inter.id,
            {"source": inter.source, "outcome": inter.outcome, "exchanges": 0},
        )
        info["exchanges"] += 1

    series = []
    for bucket in sorted(daily.values(), key=lambda b: (b["date"], b["source"], b["model"])):
        rated = bucket.pop("rated")
        rating_sum = bucket.pop("rating_sum")
        regen_sum = bucket.pop("regen_sum")
        judge_scored = bucket.pop("judge_scored")
        judge_sum = bucket.pop("judge_sum")
        exchanges = bucket["exchanges"]
        series.append(
            {
                **bucket,
                "acceptance_rate": bucket["positive"] / exchanges if exchanges else 0.0,
                "correction_rate": bucket["negative"] / exchanges if exchanges else 0.0,
                "mean_rating": rating_sum / rated if rated else None,
                "mean_regens": regen_sum / exchanges if exchanges else 0.0,
                "judge_scored": judge_scored,
                "mean_judge_score": judge_sum / judge_scored if judge_scored else None,
            }
        )

    sources: dict[str, dict[str, Any]] = {}
    for info in per_interaction.values():
        summary = sources.setdefault(
            info["source"],
            {"source": info["source"], "interactions": 0, "accepted": 0, "turns_sum": 0},
        )
        summary["interactions"] += 1
        if info["outcome"] == "accept":
            summary["accepted"] += 1
            summary["turns_sum"] += info["exchanges"]

    source_rows = []
    for summary in sorted(sources.values(), key=lambda s: str(s["source"])):
        accepted = summary.pop("accepted")
        turns_sum = summary.pop("turns_sum")
        source_rows.append(
            {
                **summary,
                "accept_rate": accepted / summary["interactions"],
                "mean_turns_to_accept": (turns_sum / accepted) if accepted else None,
            }
        )

    return {"days": days, "series": series, "sources": source_rows}
