"""Telemetry service: ingest, derivation, promotion, auto-lock, stats."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from clean_evals import telemetry_service
from clean_evals.models import Case, ModelResponse, ScoreResult
from clean_evals.storage.db import (
    CandidateOutputRow,
    CaseRow,
    DatasetRow,
    RatingRow,
    TelemetryExchangeRow,
    TelemetryInteractionRow,
    session_factory,
)

_TS = datetime(2026, 7, 10, 12, 0, tzinfo=UTC).isoformat()


def _structured_item(interaction_id: str = "int-1", **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "interaction_id": interaction_id,
        "occurred_at": _TS,
        "source": "app-prod",
        "dataset": "triage",
        "model": "claude-sonnet-5",
        "kind": "structured",
        "request": {"input": {"text": "printer broken"}},
        "response": {
            "content": '{"queue": "hardware"}',
            "parsed": {"queue": "hardware"},
        },
        "events": [{"type": "accept"}],
    }
    item.update(overrides)
    return item


def _transcript_item(interaction_id: str = "conv-1", **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "interaction_id": interaction_id,
        "occurred_at": _TS,
        "source": "app-prod",
        "dataset": "support-chat",
        "model": "claude-sonnet-5",
        "kind": "transcript",
        "turns": [
            {"role": "user", "text": "summarize this"},
            {"role": "assistant", "text": "Long summary."},
            {"role": "user", "text": "shorter please"},
            {"role": "assistant", "text": "Short summary."},
        ],
        "outcome": {"type": "accept"},
    }
    item.update(overrides)
    return item


class _StubClassifierAdapter:
    """Returns a fixed classifier labelling; never touches the network."""

    provider = "anthropic"

    def __init__(self, labels: list[dict[str, Any]] | None = None, cost: float = 0.01) -> None:
        self._labels = labels if labels is not None else [{"turn": 2, "label": "correction"}]
        self._cost = cost
        self.calls = 0

    async def complete(self, prompt: str, model: str, **kwargs: Any) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            content=json.dumps({"labels": self._labels}),
            parsed={"labels": self._labels},
            latency_ms=1,
            cost_usd=self._cost,
        )


class _StubJudge:
    """A judge scorer with a fixed verdict."""

    name = "llm_judge"

    def __init__(self, *, score: float, passed: bool) -> None:
        self._result = ScoreResult(score=score, passed=passed, breakdown={}, notes=None)
        self.calls = 0

    def score(self, case: Case, response: ModelResponse) -> ScoreResult:
        self.calls += 1
        return self._result

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> _StubJudge:
        return cls(score=1.0, passed=True)


def _derive(adapters: dict[str, Any] | None = None) -> telemetry_service.DeriveStats:
    return asyncio.run(telemetry_service.derive_pending(session_factory(), adapters=adapters))


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def test_ingest_accepts_rejects_and_deduplicates(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        result = telemetry_service.ingest_items(
            session,
            [
                _structured_item("a"),
                {"interaction_id": "broken"},  # missing everything else
                _structured_item("a"),  # duplicate within the batch
            ],
        )
        session.commit()
    assert result.accepted == 1
    assert result.duplicates == ["a"]
    assert len(result.rejected) == 1
    assert result.rejected[0]["index"] == 1

    # Retrying the whole batch is idempotent.
    with factory() as session:
        again = telemetry_service.ingest_items(session, [_structured_item("a")])
        session.commit()
    assert again.accepted == 0
    assert again.duplicates == ["a"]


def test_ingest_stores_envelope_verbatim(sqlite_engine) -> None:
    factory = session_factory()
    item = _structured_item("verbatim-1")
    with factory() as session:
        telemetry_service.ingest_items(session, [item])
        session.commit()
        row = session.execute(select(TelemetryInteractionRow)).scalar_one()
        assert row.envelope_jsonb["request"]["input"] == {"text": "printer broken"}
        assert row.outcome == "accept"
        assert row.status == "pending"


def test_misconfigured_scrubber_fails_loudly(sqlite_engine, monkeypatch) -> None:
    monkeypatch.setenv("CLEAN_EVALS_TELEMETRY_SCRUBBER", "does-not-exist")
    factory = session_factory()
    with factory() as session, pytest.raises(ValueError, match="does-not-exist"):
        telemetry_service.ingest_items(session, [_structured_item()])


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def test_derive_structured_produces_rated_exchange(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_structured_item()])
        session.commit()

    stats = _derive()
    assert stats.interactions == 1
    assert stats.exchanges == 1
    assert stats.classifier_cost_usd == 0.0

    with factory() as session:
        ex = session.execute(select(TelemetryExchangeRow)).scalar_one()
        assert ex.verdict == "positive"
        assert ex.rating == 5
        assert ex.status == "derived"
        inter = session.execute(select(TelemetryInteractionRow)).scalar_one()
        assert inter.status == "derived"


def test_derive_transcript_uses_one_classifier_call(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item()])
        session.commit()

    stub = _StubClassifierAdapter()
    stats = _derive(adapters={"anthropic": stub})
    assert stub.calls == 1
    assert stats.exchanges == 2
    assert stats.classifier_cost_usd == pytest.approx(0.01)

    with factory() as session:
        rows = (
            session.execute(select(TelemetryExchangeRow).order_by(TelemetryExchangeRow.turn_index))
            .scalars()
            .all()
        )
        # Exchange 1 was corrected by the follow-up; exchange 2 accepted at the end.
        assert rows[0].verdict == "negative"
        assert rows[0].feedback == "shorter please"
        assert rows[1].verdict == "positive"
        assert rows[1].rating == 5
        inter = session.execute(select(TelemetryInteractionRow)).scalar_one()
        assert inter.classifier_cost_usd == pytest.approx(0.01)


def test_derive_transcript_skipped_when_budget_exhausted(sqlite_engine, monkeypatch) -> None:
    monkeypatch.setenv("CLEAN_EVALS_TELEMETRY_DAILY_COST_LIMIT_USD", "0")
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item()])
        session.commit()

    stub = _StubClassifierAdapter()
    stats = _derive(adapters={"anthropic": stub})
    assert stub.calls == 0
    assert stats.skipped_budget == 1
    with factory() as session:
        inter = session.execute(select(TelemetryInteractionRow)).scalar_one()
        assert inter.status == "pending"  # retried by the next pass
        assert inter.detail is not None
        assert "ceiling" in inter.detail


def test_classifier_failure_derives_unrated(sqlite_engine) -> None:
    class _Boom:
        provider = "anthropic"

        async def complete(self, *args: Any, **kwargs: Any) -> ModelResponse:
            raise RuntimeError("provider down")

    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item()])
        session.commit()

    stats = _derive(adapters={"anthropic": _Boom()})
    assert stats.exchanges == 2
    with factory() as session:
        rows = (
            session.execute(select(TelemetryExchangeRow).order_by(TelemetryExchangeRow.turn_index))
            .scalars()
            .all()
        )
        # No labels invented: the follow-up-reviewed exchange is unrated;
        # the final one still gets its signal from the explicit accept outcome.
        assert rows[0].verdict == "unrated"
        assert rows[1].verdict == "positive"


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


def _ingest_and_derive(item: dict[str, Any]) -> int:
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [item])
        session.commit()
    _derive(adapters={"anthropic": _StubClassifierAdapter()})
    with factory() as session:
        return (
            session.execute(select(TelemetryExchangeRow.id).order_by(TelemetryExchangeRow.id))
            .scalars()
            .first()
        )


def test_promote_creates_dataset_case_candidate_and_implicit_rating(sqlite_engine) -> None:
    exchange_id = _ingest_and_derive(_structured_item())
    factory = session_factory()
    with factory() as session:
        case_pk = telemetry_service.promote_exchange(session, exchange_id, lock=True)
        session.commit()

        case = session.get(CaseRow, case_pk)
        assert case is not None
        assert case.locked is True
        assert case.expected_jsonb == {"queue": "hardware"}
        assert case.input_jsonb == {"text": "printer broken"}
        assert "telemetry" in (case.tags_jsonb or [])

        dataset = session.get(DatasetRow, case.dataset_id)
        assert dataset is not None
        assert dataset.name == "triage"
        assert dataset.version == "v1"
        # Structured cases replay through the templated shape (single field
        # renders verbatim; system travels in the system role) — the raw
        # shape would JSON-wrap the input and drop the system prompt.
        assert dataset.request_shape == "templated"

        cand = session.execute(select(CandidateOutputRow)).scalar_one()
        assert cand.model == "claude-sonnet-5"
        rating = session.execute(select(RatingRow)).scalar_one()
        assert rating.rating == 5
        assert rating.source == "implicit"

        ex = session.get(TelemetryExchangeRow, exchange_id)
        assert ex is not None
        assert ex.status == "promoted"
        assert ex.promoted_case_id == case_pk


def test_promote_duplicate_input_refused(sqlite_engine) -> None:
    first = _ingest_and_derive(_structured_item("dup-1"))
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_structured_item("dup-2")])
        session.commit()
    _derive()
    with factory() as session:
        telemetry_service.promote_exchange(session, first, lock=True)
        session.commit()
        second = (
            session.execute(
                select(TelemetryExchangeRow.id).where(TelemetryExchangeRow.status == "derived")
            )
            .scalars()
            .one()
        )
        with pytest.raises(ValueError, match="already promoted"):
            telemetry_service.promote_exchange(session, second)


def test_promote_lock_without_expected_refused(sqlite_engine) -> None:
    exchange_id = _ingest_and_derive(_structured_item(events=[]))  # no accept → no proposal
    factory = session_factory()
    with factory() as session, pytest.raises(ValueError, match="golden answer"):
        telemetry_service.promote_exchange(session, exchange_id, lock=True)


def test_promote_transcript_exchange_builds_chat_case(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item()])
        session.commit()
    _derive(adapters={"anthropic": _StubClassifierAdapter()})
    with factory() as session:
        last = (
            session.execute(
                select(TelemetryExchangeRow).order_by(TelemetryExchangeRow.turn_index.desc())
            )
            .scalars()
            .first()
        )
        assert last is not None
        case_pk = telemetry_service.promote_exchange(session, last.id, lock=True)
        session.commit()
        case = session.get(CaseRow, case_pk)
        assert case is not None
        assert case.case_id_external == "conv-1:3"
        assert case.input_jsonb["message"] == "shorter please"
        assert len(case.input_jsonb["context"]) == 2
        dataset = session.get(DatasetRow, case.dataset_id)
        assert dataset is not None
        assert dataset.request_shape == "chat"


def test_promote_structured_sets_dataset_system_prompt(sqlite_engine) -> None:
    exchange_id = _ingest_and_derive(
        _structured_item(
            request={"system": "Triage tickets. Return JSON.", "input": {"text": "vpn broken"}}
        )
    )
    factory = session_factory()
    with factory() as session:
        case_pk = telemetry_service.promote_exchange(session, exchange_id)
        session.commit()
        case = session.get(CaseRow, case_pk)
        assert case is not None
        dataset = session.get(DatasetRow, case.dataset_id)
        assert dataset is not None
        assert dataset.system_prompt == "Triage tickets. Return JSON."


def test_promote_transcript_carries_system_per_case(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item(system="Draft support replies.")])
        session.commit()
    _derive(adapters={"anthropic": _StubClassifierAdapter()})
    with factory() as session:
        last = (
            session.execute(
                select(TelemetryExchangeRow).order_by(TelemetryExchangeRow.turn_index.desc())
            )
            .scalars()
            .first()
        )
        assert last is not None
        case_pk = telemetry_service.promote_exchange(session, last.id, lock=True)
        session.commit()
        case = session.get(CaseRow, case_pk)
        assert case is not None
        assert case.input_jsonb["system"] == "Draft support replies."


def test_promote_transcript_into_non_chat_dataset_refused(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        session.add(
            DatasetRow(name="support-chat", version="v1", scorer="exact_match", scorer_config={})
        )
        telemetry_service.ingest_items(session, [_transcript_item()])
        session.commit()
    _derive(adapters={"anthropic": _StubClassifierAdapter()})
    with factory() as session:
        last = (
            session.execute(
                select(TelemetryExchangeRow).order_by(TelemetryExchangeRow.turn_index.desc())
            )
            .scalars()
            .first()
        )
        assert last is not None
        with pytest.raises(ValueError, match="chat-shaped"):
            telemetry_service.promote_exchange(session, last.id)


def test_rederive_replaces_instead_of_duplicating(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item()])
        session.commit()
    _derive(adapters={"anthropic": _StubClassifierAdapter()})
    # Simulate the race: the interaction is re-marked pending (as a
    # concurrent pass that read it before the first commit would see it).
    with factory() as session:
        inter = session.execute(select(TelemetryInteractionRow)).scalar_one()
        inter.status = "pending"
        session.commit()
    _derive(adapters={"anthropic": _StubClassifierAdapter()})
    with factory() as session:
        count = len(session.execute(select(TelemetryExchangeRow.id)).all())
        assert count == 2  # replaced, not appended


def test_promote_structured_into_chat_dataset_refused(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        session.add(
            DatasetRow(
                name="triage",
                version="v1",
                scorer="llm_judge",
                scorer_config={},
                request_shape="chat",
            )
        )
        session.commit()
    exchange_id = _ingest_and_derive(_structured_item())
    with factory() as session, pytest.raises(ValueError, match="chat-shaped"):
        telemetry_service.promote_exchange(session, exchange_id)


def test_ingest_survives_concurrent_duplicate_at_flush(sqlite_engine) -> None:
    """A duplicate that slips past the existence SELECT (committed by a
    concurrent request) must roll back that one item, not 500 the batch."""
    factory = session_factory()
    with factory() as session:
        # Pre-add the row in the same session WITHOUT flushing: the
        # existence SELECT cannot see it (autoflush is off), exactly like a
        # concurrent request's uncommitted insert, and the unique
        # constraint fires at the savepoint flush instead.
        item = _structured_item("race-1")
        session.add(
            TelemetryInteractionRow(
                interaction_id="race-1",
                source="app-prod",
                dataset_name="triage",
                kind="structured",
                model="claude-sonnet-5",
                occurred_at=datetime.now(UTC),
                outcome="accept",
                envelope_jsonb=item,
                status="pending",
            )
        )
        result = telemetry_service.ingest_items(session, [item, _structured_item("race-2")])
        session.commit()
    assert result.duplicates == ["race-1"]
    assert result.accepted == 1  # the non-duplicate item survived


def test_classifier_budget_keyed_on_spend_day_not_ingest_day(sqlite_engine, monkeypatch) -> None:
    monkeypatch.setenv("CLEAN_EVALS_TELEMETRY_DAILY_COST_LIMIT_USD", "0.01")
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item("bl-1")])
        session.commit()
        # Backdate the ingest to yesterday: the spend recorded today must
        # still count against today's ceiling.
        inter = session.execute(select(TelemetryInteractionRow)).scalar_one()
        inter.created_at = datetime.now(UTC) - timedelta(days=1)
        session.commit()
    _derive(adapters={"anthropic": _StubClassifierAdapter(cost=0.01)})

    with factory() as session:
        inter = session.execute(select(TelemetryInteractionRow)).scalar_one()
        assert inter.classified_at is not None
        assert telemetry_service.classifier_spend_today(session) == pytest.approx(0.01)

    # A second transcript now exceeds the $0.015 ceiling and is skipped.
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item("bl-2")])
        session.commit()
    stats = _derive(adapters={"anthropic": _StubClassifierAdapter(cost=0.01)})
    assert stats.skipped_budget == 1


def test_autolock_judge_never_sees_the_proposed_golden(sqlite_engine, monkeypatch) -> None:
    """The proposal IS the response for untouched accepts; handing it to the
    judge as `expected` would score the response against itself."""
    seen_expected: list[Any] = []

    class _RecordingJudge(_StubJudge):
        def score(self, case: Case, response: ModelResponse) -> ScoreResult:
            seen_expected.append(case.expected)
            return super().score(case, response)

    judge = _RecordingJudge(score=0.9, passed=True)
    _enable_autolock(monkeypatch, judge)
    _seed_dataset()
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_structured_item()])
        session.commit()
    stats = _derive()
    assert stats.auto_locked == 1
    assert seen_expected == [None]


def test_judge_for_dataset_reads_kappa_from_summary(sqlite_engine) -> None:
    from clean_evals.storage.db import JudgeConfigRow

    factory = session_factory()
    with factory() as session:
        ds = DatasetRow(name="triage", version="v1", scorer="llm_judge", scorer_config={})
        session.add(ds)
        session.flush()
        session.add(
            JudgeConfigRow(
                dataset_id=ds.id,
                version=1,
                judge_model="claude-haiku-4-5-20251001",
                rubric="r",
                few_shot_jsonb=[],
                # The shape calibration actually writes: kappa nested under
                # "summary". Reading it from the top level would make the
                # auto-lock lane permanently inoperative.
                agreement_jsonb={"summary": {"n": 12, "kappa": 0.81}, "rows": []},
            )
        )
        session.commit()
        judge = telemetry_service._judge_for_dataset(session, ds)
        assert judge is not None
        assert judge[1] == pytest.approx(0.81)


def test_discard_and_double_review_refused(sqlite_engine) -> None:
    exchange_id = _ingest_and_derive(_structured_item())
    factory = session_factory()
    with factory() as session:
        telemetry_service.discard_exchange(session, exchange_id)
        session.commit()
        with pytest.raises(ValueError, match="discarded"):
            telemetry_service.promote_exchange(session, exchange_id)


# ---------------------------------------------------------------------------
# Auto-lock lane
# ---------------------------------------------------------------------------


def _enable_autolock(monkeypatch: pytest.MonkeyPatch, judge: _StubJudge) -> None:
    monkeypatch.setenv("CLEAN_EVALS_TELEMETRY_AUTOLOCK", "1")
    monkeypatch.setenv("CLEAN_EVALS_TELEMETRY_SPOTCHECK_RATE", "1.0")
    monkeypatch.setattr(
        telemetry_service, "_judge_for_dataset", lambda session, dataset: (judge, 0.9)
    )


def _seed_dataset(name: str = "triage", request_shape: str = "templated") -> None:
    factory = session_factory()
    with factory() as session:
        session.add(
            DatasetRow(
                name=name,
                version="v1",
                scorer="llm_judge",
                scorer_config={},
                request_shape=request_shape,
            )
        )
        session.commit()


def test_autolock_promotes_when_all_signals_concur(sqlite_engine, monkeypatch) -> None:
    judge = _StubJudge(score=0.9, passed=True)
    _enable_autolock(monkeypatch, judge)
    _seed_dataset()

    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_structured_item()])
        session.commit()
    stats = _derive()
    assert stats.auto_locked == 1
    assert judge.calls == 1

    with factory() as session:
        ex = session.execute(select(TelemetryExchangeRow)).scalar_one()
        assert ex.status == "promoted"
        assert ex.auto_locked is True
        assert ex.spot_check is True  # rate forced to 1.0
        case = session.get(CaseRow, ex.promoted_case_id)
        assert case is not None
        assert case.locked is True


def test_autolock_requires_judge_concurrence(sqlite_engine, monkeypatch) -> None:
    judge = _StubJudge(score=0.2, passed=False)
    _enable_autolock(monkeypatch, judge)
    _seed_dataset()

    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_structured_item()])
        session.commit()
    stats = _derive()
    assert stats.auto_locked == 0
    with factory() as session:
        ex = session.execute(select(TelemetryExchangeRow)).scalar_one()
        assert ex.status == "derived"  # stays in the inbox for a human


def test_autolock_ignores_unrated_and_inferred_positives(sqlite_engine, monkeypatch) -> None:
    judge = _StubJudge(score=0.9, passed=True)
    _enable_autolock(monkeypatch, judge)
    _seed_dataset("support-chat", request_shape="chat")

    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_transcript_item()])
        session.commit()
    # The follow-up-labelled exchange is positive but not an explicit accept;
    # only the final (outcome=accept) exchange qualifies.
    labels = [{"turn": 2, "label": "new_request"}]
    stats = _derive(adapters={"anthropic": _StubClassifierAdapter(labels)})
    assert stats.auto_locked == 1
    with factory() as session:
        derived = (
            session.execute(
                select(TelemetryExchangeRow).where(TelemetryExchangeRow.status == "derived")
            )
            .scalars()
            .all()
        )
        assert len(derived) == 1
        assert derived[0].label == "new_request"


def test_overturned_spot_check_unlocks_case_and_disables_lane(sqlite_engine, monkeypatch) -> None:
    judge = _StubJudge(score=0.9, passed=True)
    _enable_autolock(monkeypatch, judge)
    monkeypatch.setattr(telemetry_service, "_MIN_SPOT_CHECKS_FOR_DISABLE", 1)
    _seed_dataset()

    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_structured_item("al-1")])
        session.commit()
    _derive()

    with factory() as session:
        ex = session.execute(select(TelemetryExchangeRow)).scalar_one()
        telemetry_service.resolve_spot_check(session, ex.id, overturn=True)
        session.commit()
        case = session.get(CaseRow, ex.promoted_case_id)
        assert case is not None
        assert case.locked is False
        state = telemetry_service.autolock_state(session)
        assert state["overturned"] == 1
        assert state["self_disabled"] is True

    # The lane now refuses to lock anything else.
    with factory() as session:
        telemetry_service.ingest_items(session, [_structured_item("al-2")])
        session.commit()
    stats = _derive()
    assert stats.auto_locked == 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_stats_aggregates_by_day_source_and_model(sqlite_engine) -> None:
    factory = session_factory()
    with factory() as session:
        telemetry_service.ingest_items(session, [_structured_item("s-1"), _transcript_item("t-1")])
        session.commit()
    _derive(adapters={"anthropic": _StubClassifierAdapter()})

    with factory() as session:
        stats = telemetry_service.telemetry_stats(session, days=30)
    assert stats["days"] == 30
    by_key = {(r["source"], r["model"]): r for r in stats["series"]}
    row = by_key[("app-prod", "claude-sonnet-5")]
    assert row["exchanges"] == 3  # 1 structured + 2 transcript exchanges
    assert row["positive"] == 2
    assert row["negative"] == 1
    assert row["acceptance_rate"] == pytest.approx(2 / 3)

    sources = {s["source"]: s for s in stats["sources"]}
    src = sources["app-prod"]
    assert src["interactions"] == 2
    assert src["accept_rate"] == 1.0
    # t-1 accepted after 2 exchanges, s-1 after 1 → mean 1.5.
    assert src["mean_turns_to_accept"] == pytest.approx(1.5)
