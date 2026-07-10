"""Assemble model requests from the dataset's prompt spec.

The golden path (docs/docs/flow.md) distinguishes three request shapes:

- ``raw`` — each case already contains the complete request. The case's
  single text field (or its JSON) is sent verbatim as the user message.
- ``templated`` — the dataset carries a **system prompt**, an optional
  **shared context**, and a **user template**; each case contributes only
  its variables. The system prompt travels in the provider's system role;
  context + variables render into the user message.
- ``chat`` — each case is one decision point of a conversation: prior turns
  replay verbatim as message history and the case's ``message`` becomes the
  final user message. Used by cases promoted from transcript telemetry,
  where flattening the context into one text blob would replay a different
  request than production sent.

Template placeholders (``templated`` shape):

- ``{context}`` — shared context and/or the case's ``context`` field.
- ``{case}`` — the case's variables: raw text when a single field remains
  after reserved keys, JSON otherwise.
- ``{<field>}`` — any variable by name, e.g. ``{ticket}``.

Chat case input shape:

.. code-block:: json

    {"system": "...", "context": [{"role": "user", "text": "..."}], "message": "..."}

``system`` and ``context`` are optional; ``message`` is required. Context
roles must be ``user`` or ``assistant``; ``text`` and ``content`` are both
accepted as the text key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

DEFAULT_USER_TEMPLATE = "{context}\n\n{case}"

_RESERVED_KEYS = {"id", "context"}


class ChatMessage(TypedDict):
    """One prior turn of a chat-shaped request, in provider-neutral form."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class AssembledRequest:
    """What one case sends to one model.

    ``history`` is ``None`` for single-shot shapes; for the ``chat`` shape
    it carries the prior turns that adapters replay before ``user``.
    """

    system: str | None
    user: str
    history: tuple[ChatMessage, ...] | None = None


def render_case_variables(variables: dict[str, Any]) -> str:
    """Render a case's variables as text: raw for one field, JSON for many."""
    values = {k: v for k, v in variables.items() if k not in _RESERVED_KEYS}
    if not values:
        return ""
    if len(values) == 1:
        (value,) = values.values()
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return json.dumps(values, ensure_ascii=False, indent=2)


def assemble(
    *,
    request_shape: str,
    system_prompt: str | None,
    shared_context: str | None,
    user_template: str | None,
    case_input: dict[str, Any],
) -> AssembledRequest:
    """Build the (system, user[, history]) request for one case.

    Raises:
        KeyError: When ``user_template`` names a field the case lacks.
        ValueError: When a ``chat`` case input is malformed.
    """
    if request_shape == "chat":
        return _assemble_chat(system_prompt=system_prompt, case_input=case_input)
    if request_shape != "templated":
        return AssembledRequest(system=None, user=render_case_variables(case_input))

    per_case_context = case_input.get("context")
    context_parts = [
        p.strip()
        for p in (shared_context, per_case_context if isinstance(per_case_context, str) else None)
        if isinstance(p, str) and p.strip()
    ]
    context = "\n\n".join(context_parts)

    template = user_template or DEFAULT_USER_TEMPLATE
    fields = {
        k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
        for k, v in case_input.items()
        if k not in _RESERVED_KEYS
    }
    user = template.format(context=context, case=render_case_variables(case_input), **fields)
    return AssembledRequest(
        system=system_prompt.strip() if system_prompt and system_prompt.strip() else None,
        user=user.strip(),
    )


def _assemble_chat(*, system_prompt: str | None, case_input: dict[str, Any]) -> AssembledRequest:
    """Build a chat-shaped request: history replayed verbatim + final message.

    The case's own ``system`` wins over the dataset-level system prompt —
    telemetry records the system prompt the producing application actually
    sent, and replaying anything else would change the request.
    """
    message = case_input.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("chat case input requires a non-empty string 'message' field")

    history: list[ChatMessage] = []
    raw_context = case_input.get("context") or []
    if not isinstance(raw_context, list):
        raise ValueError("chat case input 'context' must be a list of turns")
    for i, turn in enumerate(raw_context):
        if not isinstance(turn, dict):
            raise ValueError(f"chat context turn {i} must be an object")
        role = turn.get("role")
        if role not in ("user", "assistant"):
            raise ValueError(f"chat context turn {i} role must be 'user' or 'assistant'")
        text = turn.get("text", turn.get("content"))
        if not isinstance(text, str):
            raise ValueError(f"chat context turn {i} requires string 'text' (or 'content')")
        history.append({"role": role, "content": text})

    case_system = case_input.get("system")
    system = case_system if isinstance(case_system, str) and case_system.strip() else system_prompt
    return AssembledRequest(
        system=system.strip() if system and system.strip() else None,
        user=message,
        history=tuple(history) or None,
    )
