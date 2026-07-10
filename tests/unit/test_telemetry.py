"""Pure telemetry derivation: envelopes, structured edits, transcript explosion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

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

_adapter: TypeAdapter[TelemetryInteraction] = TypeAdapter(TelemetryInteraction)

_TS = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _structured(**overrides: Any) -> StructuredInteraction:
    base: dict[str, Any] = {
        "interaction_id": "int-1",
        "occurred_at": _TS.isoformat(),
        "source": "app-prod",
        "dataset": "triage",
        "model": "claude-sonnet-5",
        "kind": "structured",
        "request": {"system": "You triage tickets.", "input": {"text": "printer broken"}},
        "response": {
            "content": '{"queue": "hardware", "priority": "low"}',
            "parsed": {"queue": "hardware", "priority": "low"},
        },
        "events": [],
    }
    base.update(overrides)
    validated = _adapter.validate_python(base)
    assert isinstance(validated, StructuredInteraction)
    return validated


def _transcript(turns: list[dict[str, Any]], **overrides: Any) -> TranscriptInteraction:
    base: dict[str, Any] = {
        "interaction_id": "conv-1",
        "occurred_at": _TS.isoformat(),
        "source": "app-prod",
        "dataset": "support-chat",
        "model": "claude-sonnet-5",
        "kind": "transcript",
        "turns": turns,
    }
    base.update(overrides)
    validated = _adapter.validate_python(base)
    assert isinstance(validated, TranscriptInteraction)
    return validated


# ---------------------------------------------------------------------------
# Envelope validation
# ---------------------------------------------------------------------------


def test_interaction_id_charset_rejected() -> None:
    with pytest.raises(ValidationError):
        _structured(interaction_id="has spaces")


def test_transcript_requires_user_assistant_pair() -> None:
    with pytest.raises(ValidationError):
        _transcript([{"role": "user", "text": "hello?"}])


def test_regenerations_rejected_on_user_turns() -> None:
    with pytest.raises(ValidationError):
        _transcript(
            [
                {"role": "user", "text": "hi", "regenerations": [{"text": "x"}]},
                {"role": "assistant", "text": "hello"},
            ]
        )


def test_unknown_envelope_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        _structured(surprise="key")


# ---------------------------------------------------------------------------
# Structured derivation
# ---------------------------------------------------------------------------


def test_structured_accept_untouched_rates_five() -> None:
    ex = derive_structured(_structured(events=[{"type": "accept"}]))
    assert ex.verdict == "positive"
    assert ex.rating == 5
    assert ex.label == "accepted"
    assert ex.proposed_expected == {"queue": "hardware", "priority": "low"}
    assert ex.feedback is None


def test_structured_edits_scale_rating_and_generate_feedback() -> None:
    ex = derive_structured(
        _structured(
            events=[
                {"type": "field_edit", "field": "priority", "old": "low", "new": "high"},
                {"type": "accept"},
            ]
        )
    )
    assert ex.verdict == "positive"
    assert ex.label == "accepted_with_edits"
    # One of two fields changed; an edited output can never rate 5.
    assert ex.rating is not None
    assert 1 <= ex.rating <= 4
    assert ex.feedback is not None
    assert "`priority`" in ex.feedback
    assert "high" in ex.feedback
    # Edits are applied onto parsed when accept carries no final_output.
    assert ex.proposed_expected == {"queue": "hardware", "priority": "high"}


def test_structured_accept_final_output_wins_over_edit_replay() -> None:
    ex = derive_structured(
        _structured(
            events=[
                {"type": "field_edit", "field": "priority", "old": "low", "new": "high"},
                {"type": "accept", "final_output": {"queue": "software", "priority": "urgent"}},
            ]
        )
    )
    assert ex.proposed_expected == {"queue": "software", "priority": "urgent"}


def test_structured_without_accept_is_unrated_and_proposes_nothing() -> None:
    ex = derive_structured(
        _structured(
            events=[{"type": "field_edit", "field": "priority", "old": "low", "new": "high"}]
        )
    )
    assert ex.verdict == "unrated"
    assert ex.rating is None
    assert ex.proposed_expected is None
    # The edit is still recorded as feedback for the human reviewer.
    assert ex.feedback is not None
    assert "`priority`" in ex.feedback


def test_structured_single_string_field_renders_verbatim() -> None:
    ex = derive_structured(_structured(events=[{"type": "accept"}]))
    assert ex.request_text == "printer broken"
    assert ex.request_input == {"text": "printer broken"}


# ---------------------------------------------------------------------------
# Transcript explosion
# ---------------------------------------------------------------------------

_FOUR_TURNS = [
    {"role": "user", "text": "summarize this ticket"},
    {"role": "assistant", "text": "Long summary."},
    {"role": "user", "text": "shorter please"},
    {"role": "assistant", "text": "Short summary."},
]


def test_explode_pairs_turns_and_carries_context() -> None:
    pending = explode_transcript(_transcript(_FOUR_TURNS))
    assert [p.turn_index for p in pending] == [1, 3]
    first, second = pending
    assert first.context == []
    assert first.request_text == "summarize this ticket"
    assert first.follow_up_turn == 2
    assert first.follow_up_text == "shorter please"
    assert second.context == [
        {"role": "user", "text": "summarize this ticket"},
        {"role": "assistant", "text": "Long summary."},
    ]
    assert second.follow_up_turn is None


def test_explode_skips_assistant_without_preceding_user() -> None:
    pending = explode_transcript(
        _transcript(
            [
                {"role": "user", "text": "hi"},
                {"role": "assistant", "text": "hello"},
                {"role": "assistant", "text": "double reply"},
            ]
        )
    )
    assert [p.turn_index for p in pending] == [1]


def test_explode_counts_regenerations() -> None:
    pending = explode_transcript(
        _transcript(
            [
                {"role": "user", "text": "draft an email"},
                {
                    "role": "assistant",
                    "text": "kept draft",
                    "regenerations": [{"text": "discarded draft"}],
                },
            ]
        )
    )
    assert pending[0].regen_count == 1
    assert pending[0].alternatives[0].text == "discarded draft"


# ---------------------------------------------------------------------------
# Label finalisation
# ---------------------------------------------------------------------------


def test_correction_label_is_negative_with_feedback() -> None:
    interaction = _transcript(_FOUR_TURNS)
    derived = finalize_transcript_exchanges(
        interaction, explode_transcript(interaction), {2: "correction"}
    )
    first = derived[0]
    assert first.verdict == "negative"
    assert first.rating == 2
    assert first.feedback == "shorter please"
    assert first.proposed_expected is None


def test_new_request_label_implicitly_accepts_and_proposes() -> None:
    interaction = _transcript(_FOUR_TURNS)
    derived = finalize_transcript_exchanges(
        interaction, explode_transcript(interaction), {2: "new_request"}
    )
    first = derived[0]
    assert first.verdict == "positive"
    assert first.rating == 4
    assert first.proposed_expected == {"text": "Long summary."}


def test_clarification_reply_is_incomplete() -> None:
    interaction = _transcript(_FOUR_TURNS)
    derived = finalize_transcript_exchanges(
        interaction, explode_transcript(interaction), {2: "clarification_reply"}
    )
    assert derived[0].verdict == "incomplete"
    assert derived[0].rating is None


def test_final_exchange_signal_comes_from_accept_outcome() -> None:
    interaction = _transcript(_FOUR_TURNS, outcome={"type": "accept"})
    derived = finalize_transcript_exchanges(interaction, explode_transcript(interaction), {})
    last = derived[-1]
    assert last.verdict == "positive"
    assert last.rating == 5
    assert last.label == "accepted"
    assert last.proposed_expected == {"text": "Short summary."}


def test_ended_transcript_leaves_final_exchange_unrated() -> None:
    interaction = _transcript(_FOUR_TURNS, outcome={"type": "ended"})
    derived = finalize_transcript_exchanges(interaction, explode_transcript(interaction), {})
    assert derived[-1].verdict == "unrated"
    assert derived[-1].rating is None
    assert derived[-1].proposed_expected is None


def test_missing_label_degrades_to_unrated() -> None:
    interaction = _transcript(_FOUR_TURNS)
    derived = finalize_transcript_exchanges(interaction, explode_transcript(interaction), {})
    assert derived[0].verdict == "unrated"


def test_regenerations_lower_the_rating() -> None:
    turns = [
        {"role": "user", "text": "draft"},
        {
            "role": "assistant",
            "text": "kept",
            "regenerations": [{"text": "a"}, {"text": "b"}],
        },
    ]
    interaction = _transcript(turns, outcome={"type": "accept"})
    derived = finalize_transcript_exchanges(interaction, explode_transcript(interaction), {})
    assert derived[0].rating == 3  # 5 - 2 regenerations


def test_input_hash_distinguishes_context() -> None:
    interaction = _transcript(_FOUR_TURNS, outcome={"type": "accept"})
    derived = finalize_transcript_exchanges(interaction, explode_transcript(interaction), {})
    assert derived[0].input_hash != derived[1].input_hash


# ---------------------------------------------------------------------------
# Classifier prompt + label parsing
# ---------------------------------------------------------------------------


def test_classifier_prompt_lists_turns_and_targets_follow_ups() -> None:
    prompt, to_label = build_classifier_prompt(_transcript(_FOUR_TURNS))
    assert to_label == [2]
    assert "[2] user: shorter please" in prompt


def test_parse_classifier_labels_drops_garbage() -> None:
    labels = parse_classifier_labels(
        {
            "labels": [
                {"turn": 2, "label": "correction"},
                {"turn": 99, "label": "correction"},  # unexpected turn
                {"turn": 2, "label": "made_up"},  # unknown label (overwrites? no — dropped)
                "not a dict",
            ]
        },
        expected_turns=[2],
    )
    assert labels == {2: "correction"}


def test_parse_classifier_labels_handles_non_list() -> None:
    assert parse_classifier_labels({"labels": "nope"}, expected_turns=[2]) == {}
    assert parse_classifier_labels({}, expected_turns=[2]) == {}
