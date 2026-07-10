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


def test_chat_shape_replays_context_as_history() -> None:
    req = assemble(
        request_shape="chat",
        system_prompt=None,
        shared_context=None,
        user_template=None,
        case_input={
            "system": "You summarize.",
            "context": [
                {"role": "user", "text": "summarize this"},
                {"role": "assistant", "text": "Long summary."},
            ],
            "message": "shorter please",
        },
    )
    assert req.system == "You summarize."
    assert req.user == "shorter please"
    assert req.history == (
        {"role": "user", "content": "summarize this"},
        {"role": "assistant", "content": "Long summary."},
    )


def test_chat_shape_case_system_wins_over_dataset_prompt() -> None:
    req = assemble(
        request_shape="chat",
        system_prompt="dataset-level",
        shared_context=None,
        user_template=None,
        case_input={"system": "case-level", "message": "hi"},
    )
    assert req.system == "case-level"


def test_chat_shape_without_context_has_no_history() -> None:
    req = assemble(
        request_shape="chat",
        system_prompt=None,
        shared_context=None,
        user_template=None,
        case_input={"message": "hi"},
    )
    assert req.history is None


def test_chat_shape_requires_message() -> None:
    with pytest.raises(ValueError, match="message"):
        assemble(
            request_shape="chat",
            system_prompt=None,
            shared_context=None,
            user_template=None,
            case_input={"context": []},
        )


def test_chat_shape_rejects_bad_roles() -> None:
    with pytest.raises(ValueError, match="role"):
        assemble(
            request_shape="chat",
            system_prompt=None,
            shared_context=None,
            user_template=None,
            case_input={"context": [{"role": "system", "text": "x"}], "message": "hi"},
        )


def test_chat_shape_merges_consecutive_same_role_turns() -> None:
    """Anthropic and Google reject non-alternating roles; merged turns are
    what they would have accepted from the producing application."""
    req = assemble(
        request_shape="chat",
        system_prompt=None,
        shared_context=None,
        user_template=None,
        case_input={
            "context": [
                {"role": "user", "text": "first"},
                {"role": "user", "text": "second"},
                {"role": "assistant", "text": "reply"},
            ],
            "message": "follow up",
        },
    )
    assert req.history == (
        {"role": "user", "content": "first\n\nsecond"},
        {"role": "assistant", "content": "reply"},
    )
    assert req.user == "follow up"


def test_chat_shape_folds_trailing_user_turn_into_message() -> None:
    req = assemble(
        request_shape="chat",
        system_prompt=None,
        shared_context=None,
        user_template=None,
        case_input={
            "context": [
                {"role": "user", "text": "hi"},
                {"role": "assistant", "text": "hello"},
                {"role": "user", "text": "one more thing"},
            ],
            "message": "actually, do this",
        },
    )
    assert req.history == (
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    )
    assert req.user == "one more thing\n\nactually, do this"
