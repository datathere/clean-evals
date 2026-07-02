"""Assemble model requests from the dataset's prompt spec.

The golden path (docs/docs/flow.md) distinguishes two request shapes:

- ``raw`` — each case already contains the complete request. The case's
  single text field (or its JSON) is sent verbatim as the user message.
- ``templated`` — the dataset carries a **system prompt**, an optional
  **shared context**, and a **user template**; each case contributes only
  its variables. The system prompt travels in the provider's system role;
  context + variables render into the user message.

Template placeholders:

- ``{context}`` — shared context and/or the case's ``context`` field.
- ``{case}`` — the case's variables: raw text when a single field remains
  after reserved keys, JSON otherwise.
- ``{<field>}`` — any variable by name, e.g. ``{ticket}``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

DEFAULT_USER_TEMPLATE = "{context}\n\n{case}"

_RESERVED_KEYS = {"id", "context"}


@dataclass(frozen=True, slots=True)
class AssembledRequest:
    """What one case sends to one model."""

    system: str | None
    user: str


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
    """Build the (system, user) pair for one case.

    Raises:
        KeyError: When ``user_template`` names a field the case lacks.
    """
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
