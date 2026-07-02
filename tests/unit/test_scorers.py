"""Tests for built-in scorers (excluding LLM judge — see test_llm_judge.py)."""

from __future__ import annotations

from clean_evals.models import Case, ModelResponse
from clean_evals.scorers.exact_match import ExactMatchScorer
from clean_evals.scorers.json_field_match import JsonFieldMatchScorer


def _resp(text: str = "", parsed: dict | None = None) -> ModelResponse:
    return ModelResponse(content=text, parsed=parsed, latency_ms=0, cost_usd=0.0)


# ---------------------------------------------------------------------------
# ExactMatch
# ---------------------------------------------------------------------------


def test_exact_match_basic() -> None:
    scorer = ExactMatchScorer.from_config({"field": "label"})
    case = Case(id="c", input={}, expected={"label": "Positive"})
    assert scorer.score(case, _resp("positive")).score == 1.0
    assert scorer.score(case, _resp("negative")).score == 0.0


def test_exact_match_strip_and_case() -> None:
    scorer = ExactMatchScorer.from_config({"field": "label"})
    case = Case(id="c", input={}, expected={"label": "yes"})
    assert scorer.score(case, _resp("  YES  ")).passed


def test_exact_match_case_sensitive() -> None:
    scorer = ExactMatchScorer.from_config({"field": "label", "case_sensitive": True})
    case = Case(id="c", input={}, expected={"label": "Yes"})
    assert not scorer.score(case, _resp("yes")).passed
    assert scorer.score(case, _resp("Yes")).passed


def test_exact_match_uses_parsed_when_field_set() -> None:
    scorer = ExactMatchScorer.from_config({"field": "label"})
    case = Case(id="c", input={}, expected={"label": "hi"})
    resp = _resp(text="ignored", parsed={"label": "hi"})
    assert scorer.score(case, resp).passed


# ---------------------------------------------------------------------------
# JsonFieldMatch
# ---------------------------------------------------------------------------


def test_json_field_match_full_match() -> None:
    scorer = JsonFieldMatchScorer.from_config({})
    case = Case(id="c", input={}, expected={"a": 1, "b": "two"})
    resp = _resp(parsed={"a": 1, "b": "two"})
    out = scorer.score(case, resp)
    assert out.score == 1.0
    assert out.passed


def test_json_field_match_partial() -> None:
    scorer = JsonFieldMatchScorer.from_config({"pass_threshold": 0.6})
    case = Case(id="c", input={}, expected={"a": 1, "b": "two"})
    resp = _resp(parsed={"a": 1, "b": "wrong"})
    out = scorer.score(case, resp)
    assert out.score == 0.5
    assert not out.passed


def test_json_field_match_weights() -> None:
    scorer = JsonFieldMatchScorer.from_config(
        {"weights": {"a": 3.0, "b": 1.0}, "pass_threshold": 0.7}
    )
    case = Case(id="c", input={}, expected={"a": 1, "b": "two"})
    # A right, B wrong — weight 3 vs 1, expect 0.75
    resp = _resp(parsed={"a": 1, "b": "wrong"})
    out = scorer.score(case, resp)
    assert abs(out.score - 0.75) < 1e-9
    assert out.passed


def test_json_field_match_list_set_semantics() -> None:
    scorer = JsonFieldMatchScorer.from_config({"list_as_set": True})
    case = Case(id="c", input={}, expected={"tags": ["a", "b", "c"]})
    resp = _resp(parsed={"tags": ["c", "a", "b"]})
    out = scorer.score(case, resp)
    assert out.score == 1.0


def test_json_field_match_list_ordered() -> None:
    scorer = JsonFieldMatchScorer.from_config({"list_as_set": False})
    case = Case(id="c", input={}, expected={"tags": ["a", "b"]})
    out = scorer.score(case, _resp(parsed={"tags": ["b", "a"]}))
    assert out.score == 0.0


def test_json_field_match_rel_tol_for_floats() -> None:
    scorer = JsonFieldMatchScorer.from_config({"rel_tol": 0.01})
    case = Case(id="c", input={}, expected={"x": 1.0})
    out = scorer.score(case, _resp(parsed={"x": 1.005}))
    assert out.score == 1.0


def test_json_field_match_no_expected() -> None:
    scorer = JsonFieldMatchScorer.from_config({})
    case = Case(id="c", input={}, expected=None)
    out = scorer.score(case, _resp(parsed={"x": 1}))
    assert out.score == 0.0
    assert "no expected" in (out.notes or "")
