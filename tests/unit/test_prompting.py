"""Tests for prompt assembly (docs/docs/flow.md, stage 1)."""

from __future__ import annotations

import pytest

from clean_evals.prompting import assemble, render_case_variables


def test_raw_shape_single_field_sends_verbatim() -> None:
    req = assemble(
        request_shape="raw",
        system_prompt=None,
        shared_context=None,
        user_template=None,
        case_input={"prompt": "hello"},
    )
    assert req.system is None
    assert req.user == "hello"


def test_raw_shape_many_fields_sends_json() -> None:
    req = assemble(
        request_shape="raw",
        system_prompt=None,
        shared_context=None,
        user_template=None,
        case_input={"a": 1, "b": "two"},
    )
    assert '"a": 1' in req.user
    assert '"b": "two"' in req.user


def test_templated_shape_splits_system_and_user() -> None:
    req = assemble(
        request_shape="templated",
        system_prompt="You are a support agent.",
        shared_context="Policy: refunds within 30 days.",
        user_template=None,
        case_input={"id": "t1", "ticket": "Charged twice"},
    )
    assert req.system == "You are a support agent."
    assert "Policy: refunds within 30 days." in req.user
    assert "Charged twice" in req.user
    # System prompt must NOT leak into the user message.
    assert "support agent" not in req.user


def test_templated_per_case_context_appends_to_shared() -> None:
    req = assemble(
        request_shape="templated",
        system_prompt="s",
        shared_context="shared base",
        user_template=None,
        case_input={"context": "retrieved chunk", "q": "why?"},
    )
    assert "shared base" in req.user
    assert "retrieved chunk" in req.user
    assert req.user.index("shared base") < req.user.index("retrieved chunk")


def test_templated_named_placeholders() -> None:
    req = assemble(
        request_shape="templated",
        system_prompt="s",
        shared_context=None,
        user_template="Ticket: {ticket}\nTier: {tier}",
        case_input={"ticket": "Broken", "tier": "gold"},
    )
    assert req.user == "Ticket: Broken\nTier: gold"


def test_templated_missing_placeholder_raises() -> None:
    with pytest.raises(KeyError):
        assemble(
            request_shape="templated",
            system_prompt=None,
            shared_context=None,
            user_template="{nope}",
            case_input={"ticket": "x"},
        )


def test_render_case_variables_excludes_reserved_keys() -> None:
    assert render_case_variables({"id": "a", "context": "c", "msg": "hi"}) == "hi"
