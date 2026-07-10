"""Telemetry envelope models and pure derivation.

Production telemetry enters clean-evals as *interactions* — one envelope per
real user interaction with a model. Two kinds exist:

- ``structured`` — a single request/response where the user then edited
  fields of the output (or accepted it whole). Derivation is deterministic
  and free: the edit ratio becomes an implicit 1–5 rating, the diffs become
  feedback text, and the accepted output becomes the proposed golden answer.
- ``transcript`` — a whole conversation, verbatim. Derivation *explodes* the
  transcript into exchanges: each (user turn, assistant turn) pair is one
  data point, with all prior turns as its context. The next user message is
  the review of the previous response; an LLM classifier labels each
  follow-up (see :data:`FOLLOW_UP_LABELS`) and the label maps to a verdict
  and rating here.

Everything in this module is pure — no I/O, no storage. Persistence and the
classifier call live in :mod:`clean_evals.telemetry_service`. Envelopes are
part of the public API surface (the ingest endpoint accepts them verbatim),
so the models follow the same rules as :mod:`clean_evals.models`: strict,
``extra="forbid"``, field additions ratchet a minor version.

Model ids in envelopes are stored verbatim. Production applications may use
floating aliases; the dated-snapshot rule applies to eval runs, not to
recording what actually happened.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Envelope models
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_ID_RE = re.compile(r"^[A-Za-z0-9_.\-:]+$")

#: Labels the transcript classifier assigns to each follow-up user message.
#: A follow-up is the user's review of the previous assistant response.
FOLLOW_UP_LABELS = (
    "correction",  # "no, shorter" — the previous response was wrong or unusable
    "accept_with_correction",  # "thanks, but fix the date" — usable, needs a fix
    "new_request",  # "great, now translate it" — implicit accept, new task
    "clarification_reply",  # the assistant asked; the exchange is incomplete
    "acceptance",  # explicit praise or acceptance
)

FollowUpLabel = Literal[
    "correction",
    "accept_with_correction",
    "new_request",
    "clarification_reply",
    "acceptance",
]

Verdict = Literal["positive", "negative", "incomplete", "unrated"]


class TelemetryRequest(_StrictModel):
    """The initial request of a ``structured`` interaction."""

    system: str | None = None
    input: dict[str, Any]


class TelemetryResponse(_StrictModel):
    """The model's response in a ``structured`` interaction."""

    content: str = ""
    parsed: dict[str, Any] | None = None


class FieldEditEvent(_StrictModel):
    """The user changed one field of a structured output."""

    type: Literal["field_edit"]
    field: str
    old: Any = None
    new: Any = None
    at: datetime | None = None


class AcceptEvent(_StrictModel):
    """The user committed the output (Save / Send / Apply).

    ``final_output`` is the output as committed — after any edits. When
    omitted, derivation applies the recorded field edits to the response's
    ``parsed`` value instead.
    """

    type: Literal["accept"]
    final_output: dict[str, Any] | None = None
    at: datetime | None = None


StructuredEvent = Annotated[FieldEditEvent | AcceptEvent, Field(discriminator="type")]


class Regeneration(_StrictModel):
    """A discarded alternative for the same request (the user hit retry)."""

    text: str
    model: str | None = None


class TranscriptTurn(_StrictModel):
    """One turn of a ``transcript`` interaction, verbatim.

    ``regenerations`` on an assistant turn holds discarded alternatives for
    the same request; ``text`` is the response the user kept.
    """

    role: Literal["user", "assistant"]
    text: str
    at: datetime | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    regenerations: list[Regeneration] = Field(default_factory=list)

    @model_validator(mode="after")
    def _regenerations_on_assistant_only(self) -> TranscriptTurn:
        if self.role == "user" and self.regenerations:
            raise ValueError("regenerations are only valid on assistant turns")
        return self


class Outcome(_StrictModel):
    """How the interaction ended.

    ``accept`` requires a real commit action in the producing application
    (Save / Send / Apply). ``ended`` means the transcript simply stopped —
    satisfaction and abandonment look identical there, so the final exchange
    stays unrated rather than being guessed at.
    """

    type: Literal["accept", "ended"]
    final_output: dict[str, Any] | None = None
    at: datetime | None = None


class _InteractionBase(_StrictModel):
    interaction_id: str
    occurred_at: datetime
    source: str
    dataset: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("interaction_id")
    @classmethod
    def _validate_interaction_id(cls, v: str) -> str:
        if not v or len(v) > 80:
            raise ValueError("interaction_id must be 1-80 characters")
        if not _ID_RE.match(v):
            raise ValueError(
                f"interaction_id {v!r} contains illegal characters; allowed: A-Z a-z 0-9 _ - . :"
            )
        return v

    @field_validator("source", "dataset", "model")
    @classmethod
    def _validate_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("value may not be empty")
        return v.strip()


class StructuredInteraction(_InteractionBase):
    """A single-shot request/response with field-edit events."""

    kind: Literal["structured"] = "structured"
    request: TelemetryRequest
    response: TelemetryResponse
    events: list[StructuredEvent] = Field(default_factory=list)


class TranscriptInteraction(_InteractionBase):
    """A whole conversation, verbatim, plus how it ended."""

    kind: Literal["transcript"] = "transcript"
    system: str | None = None
    turns: list[TranscriptTurn]
    outcome: Outcome | None = None

    @model_validator(mode="after")
    def _validate_turns(self) -> TranscriptInteraction:
        if not any(
            turn.role == "assistant" and i > 0 and self.turns[i - 1].role == "user"
            for i, turn in enumerate(self.turns)
        ):
            raise ValueError("transcript must contain at least one user→assistant pair")
        return self


TelemetryInteraction = Annotated[
    StructuredInteraction | TranscriptInteraction, Field(discriminator="kind")
]


# ---------------------------------------------------------------------------
# Derived exchanges
# ---------------------------------------------------------------------------


class DerivedExchange(_StrictModel):
    """One (request, response) data point derived from an interaction.

    Attributes:
        turn_index: Index of the assistant turn within the transcript
            (``0`` for structured interactions).
        context: Prior turns as ``{"role", "text"}`` dicts, verbatim.
        request_text: The user message of this exchange (rendered text for
            structured interactions).
        request_input: The original structured input, when the interaction
            was structured — promotion uses it as ``Case.input`` unchanged.
        verdict: ``positive`` (usable as-is), ``negative`` (corrected),
            ``incomplete`` (the assistant asked a question), ``unrated``
            (no signal — never guessed at).
        rating: Implicit 1–5 rating, or ``None`` when unrated/incomplete.
        proposed_expected: Proposed golden answer. Only positive exchanges
            propose their own response; a corrected response's eventual
            replacement satisfies *refined* constraints the original request
            never stated, so it is not proposed for the original input.
        input_hash: Content hash over (dataset, context, request) used for
            promotion-time dedup.
    """

    turn_index: int
    context: list[dict[str, str]] = Field(default_factory=list)
    request_text: str
    request_input: dict[str, Any] | None = None
    response_text: str
    response_parsed: dict[str, Any] | None = None
    response_model: str
    alternatives: list[Regeneration] = Field(default_factory=list)
    regen_count: int = 0
    label: str | None = None
    verdict: Verdict
    rating: int | None = None
    feedback: str | None = None
    proposed_expected: dict[str, Any] | None = None
    input_hash: str


def _hash_exchange(dataset: str, context: list[dict[str, str]], request: str) -> str:
    payload = json.dumps(
        {"dataset": dataset, "context": context, "request": request},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clip(value: Any, limit: int = 80) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clamp_rating(value: int) -> int:
    return max(1, min(5, value))


# ---------------------------------------------------------------------------
# Structured derivation — deterministic and free
# ---------------------------------------------------------------------------


def derive_structured(interaction: StructuredInteraction) -> DerivedExchange:
    """Derive the single exchange of a structured interaction.

    Rating scale: an untouched accept is 5; edits scale the rating down by
    the fraction of fields changed, capped at 4 (an edited output is by
    definition not a perfect one). Without an accept event the exchange is
    ``unrated`` — the absence of a commit action is not treated as approval.
    """
    edits = [e for e in interaction.events if isinstance(e, FieldEditEvent)]
    accept = next(
        (e for e in reversed(interaction.events) if isinstance(e, AcceptEvent)),
        None,
    )
    edited_fields = list(dict.fromkeys(e.field for e in edits))

    final_output: dict[str, Any] | None = None
    if accept is not None:
        if accept.final_output is not None:
            final_output = accept.final_output
        elif interaction.response.parsed is not None:
            final_output = dict(interaction.response.parsed)
            for edit in edits:
                final_output[edit.field] = edit.new

    request_text = _render_input(interaction.request.input)
    feedback = (
        "; ".join(f"changed `{e.field}`: {_clip(e.old)} → {_clip(e.new)}" for e in edits) or None
    )

    verdict: Verdict
    rating: int | None
    label: str | None
    if accept is None:
        verdict, rating, label = "unrated", None, None
        proposed = None
    elif not edited_fields:
        verdict, rating, label = "positive", 5, "accepted"
        proposed = final_output or interaction.response.parsed
    else:
        fields_total = max(
            len(final_output or interaction.response.parsed or {}),
            len(edited_fields),
            1,
        )
        unchanged = 1.0 - (len(edited_fields) / fields_total)
        verdict = "positive"
        rating = min(4, _clamp_rating(1 + round(4 * unchanged)))
        label = "accepted_with_edits"
        proposed = final_output

    return DerivedExchange(
        turn_index=0,
        context=[],
        request_text=request_text,
        request_input=dict(interaction.request.input),
        response_text=interaction.response.content,
        response_parsed=interaction.response.parsed,
        response_model=interaction.model,
        verdict=verdict,
        rating=rating,
        label=label,
        feedback=feedback,
        proposed_expected=proposed,
        input_hash=_hash_exchange(interaction.dataset, [], request_text),
    )


def _render_input(value: dict[str, Any]) -> str:
    if len(value) == 1:
        (single,) = value.values()
        if isinstance(single, str):
            return single
    return json.dumps(value, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Transcript explosion
# ---------------------------------------------------------------------------


class PendingExchange(_StrictModel):
    """An exchange awaiting its follow-up label from the classifier.

    ``follow_up_turn`` is the index of the user turn that reviews this
    exchange's response — the turn *immediately* after it, and only when
    that turn is a user turn. ``is_final`` is true when this exchange's
    response is the transcript's last assistant turn; only then may the
    terminal outcome speak for it. When trailing assistant turns were
    skipped (no user request to pair them with), the outcome describes
    those, and no exchange inherits it.
    """

    turn_index: int
    context: list[dict[str, str]]
    request_text: str
    response_text: str
    response_model: str
    alternatives: list[Regeneration] = Field(default_factory=list)
    regen_count: int = 0
    follow_up_turn: int | None = None
    follow_up_text: str | None = None
    is_final: bool = False


def explode_transcript(interaction: TranscriptInteraction) -> list[PendingExchange]:
    """Split a transcript into per-turn exchanges.

    For turns ``u1 a1 u2 a2 u3 a3``: exchange *k* pairs user turn *k* with
    the assistant turn that immediately follows it, carries all prior turns
    as context, and is reviewed by the user turn immediately after it (the
    final exchange by the terminal outcome). Assistant turns without an
    immediately preceding user turn are skipped — there is no request to
    pair them with — and a user message that follows a *different* assistant
    turn is never attributed to an earlier exchange: a reaction reviews the
    response it actually followed.
    """
    exchanges: list[PendingExchange] = []
    turns = interaction.turns
    last_assistant = max(
        (i for i, turn in enumerate(turns) if turn.role == "assistant"), default=-1
    )
    for i, turn in enumerate(turns):
        if turn.role != "assistant" or i == 0 or turns[i - 1].role != "user":
            continue
        follow_up = i + 1 if i + 1 < len(turns) and turns[i + 1].role == "user" else None
        exchanges.append(
            PendingExchange(
                turn_index=i,
                context=[{"role": t.role, "text": t.text} for t in turns[: i - 1]],
                request_text=turns[i - 1].text,
                response_text=turn.text,
                response_model=turn.model or interaction.model,
                alternatives=list(turn.regenerations),
                regen_count=len(turn.regenerations),
                follow_up_turn=follow_up,
                follow_up_text=turns[follow_up].text if follow_up is not None else None,
                is_final=i == last_assistant,
            )
        )
    return exchanges


#: label → (verdict, base rating before the regeneration penalty,
#:          feedback from the follow-up text, propose own response as golden)
_LABEL_RULES: dict[str, tuple[Verdict, int | None, bool, bool]] = {
    "correction": ("negative", 2, True, False),
    "accept_with_correction": ("positive", 4, True, False),
    "new_request": ("positive", 4, False, True),
    "clarification_reply": ("incomplete", None, False, False),
    "acceptance": ("positive", 5, True, True),
}


def finalize_transcript_exchanges(
    interaction: TranscriptInteraction,
    pending: list[PendingExchange],
    labels: dict[int, str],
) -> list[DerivedExchange]:
    """Apply follow-up labels (and the terminal outcome) to pending exchanges.

    Args:
        pending: Output of :func:`explode_transcript`.
        labels: Classifier labels keyed by user-turn index. Unknown or
            missing labels degrade to ``unrated`` — a classifier failure
            never invents a signal.

    Each regeneration on an exchange lowers its rating by one point
    (floor 1): retrying is a strong negative signal in both directions.
    """
    derived: list[DerivedExchange] = []
    for ex in pending:
        verdict: Verdict
        rating: int | None
        label: str | None
        feedback: str | None = None
        proposed: dict[str, Any] | None = None

        if ex.follow_up_turn is not None:
            label = labels.get(ex.follow_up_turn)
            rule = _LABEL_RULES.get(label or "")
            if rule is None:
                verdict, rating, label = "unrated", None, None
            else:
                verdict, base, use_feedback, propose = rule
                rating = _clamp_rating(base - ex.regen_count) if base is not None else None
                feedback = ex.follow_up_text if use_feedback else None
                proposed = {"text": ex.response_text} if propose else None
        elif (
            ex.is_final and interaction.outcome is not None and interaction.outcome.type == "accept"
        ):
            # The terminal outcome speaks only for the transcript's last
            # exchange; an earlier exchange without an immediate user
            # reaction has no signal of its own.
            verdict, label = "positive", "accepted"
            rating = _clamp_rating(5 - ex.regen_count)
            proposed = interaction.outcome.final_output or {"text": ex.response_text}
        else:
            verdict, rating, label = "unrated", None, None

        derived.append(
            DerivedExchange(
                turn_index=ex.turn_index,
                context=ex.context,
                request_text=ex.request_text,
                response_text=ex.response_text,
                response_model=ex.response_model,
                alternatives=ex.alternatives,
                regen_count=ex.regen_count,
                label=label,
                verdict=verdict,
                rating=rating,
                feedback=feedback,
                proposed_expected=proposed,
                input_hash=_hash_exchange(interaction.dataset, ex.context, ex.request_text),
            )
        )
    return derived


# ---------------------------------------------------------------------------
# Classifier prompt — one call per transcript
# ---------------------------------------------------------------------------

CLASSIFIER_PROMPT_TEMPLATE = """\
You are analyzing a conversation between a user and an AI assistant.

Each user message AFTER an assistant response is that user's reaction to the
response. Label every such user message with exactly one of:

- "correction" — the user says the response was wrong or unusable and asks
  for something different ("no, shorter", "that's wrong").
- "accept_with_correction" — the user accepts the response but asks for a
  fix ("thanks, but fix the date").
- "new_request" — the user moves on to a new task, implicitly accepting the
  previous response ("great, now translate it").
- "clarification_reply" — the assistant asked a question and the user is
  answering it.
- "acceptance" — the user explicitly accepts or praises the response.

CONVERSATION (turns are numbered; label only user turns that follow an
assistant turn):

{transcript}

Return ONLY a JSON object of the form
{{"labels": [{{"turn": <turn number>, "label": "<one of the five labels>"}}]}}
with one entry per user turn listed above. No prose.
"""


def build_classifier_prompt(interaction: TranscriptInteraction) -> tuple[str, list[int]]:
    """Render the classifier prompt and the user-turn indices it must label."""
    lines: list[str] = []
    to_label: list[int] = []
    for i, turn in enumerate(interaction.turns):
        lines.append(f"[{i}] {turn.role}: {turn.text}")
        if turn.role == "user" and i > 0 and interaction.turns[i - 1].role == "assistant":
            to_label.append(i)
    return CLASSIFIER_PROMPT_TEMPLATE.format(transcript="\n".join(lines)), to_label


def parse_classifier_labels(parsed: dict[str, Any], expected_turns: list[int]) -> dict[int, str]:
    """Extract ``{turn: label}`` from the classifier's JSON, dropping garbage.

    Entries with unknown labels or unexpected turn numbers are discarded;
    the affected exchanges then derive as ``unrated``. A misbehaving
    classifier degrades signal, never fabricates it.
    """
    labels: dict[int, str] = {}
    raw = parsed.get("labels")
    if not isinstance(raw, list):
        return labels
    expected = set(expected_turns)
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        turn = entry.get("turn")
        label = entry.get("label")
        if isinstance(turn, int) and turn in expected and label in FOLLOW_UP_LABELS:
            labels[turn] = label
    return labels
