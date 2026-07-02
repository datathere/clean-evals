"""Per-field equality scorer for structured (JSON) outputs.

For each field in ``case.expected``, awards 1.0 if the model's
``response.parsed`` value at the same key compares equal, otherwise 0.0.
The aggregate score is the mean of per-field scores. Optional weights let
some fields count more than others.

Comparison semantics:

- Strings compared with optional ``strip``/``case_sensitive`` (defaults
  ``true``/``false``).
- Numbers compared with optional ``rel_tol`` for floats (default ``0``,
  i.e. exact equality).
- Lists compared element-wise after sorting (set equality) when
  ``list_as_set`` is true (default ``true``); ordered when ``false``.
- Nested dicts compared recursively with the same rules.

Configuration:

.. code-block:: yaml

    scorer: json_field_match
    scorer_config:
      weights: { name: 1.0, type: 0.5 }
      strip: true
      case_sensitive: false
      list_as_set: true
      rel_tol: 0.001
      pass_threshold: 0.8
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from clean_evals.models import Case, ModelResponse, ScoreResult


class JsonFieldMatchScorer:
    name: ClassVar[str] = "json_field_match"

    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        strip: bool = True,
        case_sensitive: bool = False,
        list_as_set: bool = True,
        rel_tol: float = 0.0,
        pass_threshold: float = 0.8,
    ) -> None:
        self._weights = weights or {}
        self._strip = strip
        self._case_sensitive = case_sensitive
        self._list_as_set = list_as_set
        self._rel_tol = rel_tol
        self._pass_threshold = pass_threshold

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> JsonFieldMatchScorer:
        return cls(
            weights=dict(config.get("weights") or {}),
            strip=bool(config.get("strip", True)),
            case_sensitive=bool(config.get("case_sensitive", False)),
            list_as_set=bool(config.get("list_as_set", True)),
            rel_tol=float(config.get("rel_tol", 0.0)),
            pass_threshold=float(config.get("pass_threshold", 0.8)),
        )

    def score(self, case: Case, response: ModelResponse) -> ScoreResult:
        expected = case.expected or {}
        actual = response.parsed or {}
        if not expected:
            return ScoreResult(score=0.0, passed=False, breakdown={}, notes="no expected fields")

        breakdown: dict[str, float] = {}
        weighted_total = 0.0
        weight_sum = 0.0
        for field, exp_value in expected.items():
            act_value = actual.get(field)
            field_score = self._compare(exp_value, act_value)
            breakdown[field] = field_score
            weight = float(self._weights.get(field, 1.0))
            weighted_total += field_score * weight
            weight_sum += weight

        score = weighted_total / weight_sum if weight_sum > 0 else 0.0
        return ScoreResult(
            score=score,
            passed=score >= self._pass_threshold,
            breakdown=breakdown,
            notes=None,
        )

    def _compare(self, expected: Any, actual: Any) -> float:
        if expected is None and actual is None:
            return 1.0
        if isinstance(expected, dict) and isinstance(actual, dict):
            if not expected:
                return 1.0 if not actual else 0.0
            inner: list[float] = []
            for k, v in expected.items():
                inner.append(self._compare(v, actual.get(k)))
            return sum(inner) / len(inner)
        if isinstance(expected, list) and isinstance(actual, list):
            return self._compare_lists(expected, actual)
        if isinstance(expected, str) and isinstance(actual, str):
            a, b = expected, actual
            if self._strip:
                a, b = a.strip(), b.strip()
            if not self._case_sensitive:
                a, b = a.lower(), b.lower()
            return 1.0 if a == b else 0.0
        if isinstance(expected, bool) or isinstance(actual, bool):
            return 1.0 if expected == actual else 0.0
        if isinstance(expected, int | float) and isinstance(actual, int | float):
            if self._rel_tol > 0 and math.isclose(
                float(expected), float(actual), rel_tol=self._rel_tol, abs_tol=self._rel_tol
            ):
                return 1.0
            return 1.0 if expected == actual else 0.0
        return 1.0 if expected == actual else 0.0

    def _compare_lists(self, expected: list[Any], actual: list[Any]) -> float:
        if not expected:
            return 1.0 if not actual else 0.0
        if self._list_as_set:
            try:
                exp_set = {self._canon(x) for x in expected}
                act_set = {self._canon(x) for x in actual}
            except TypeError:
                # Fall through to ordered if elements aren't hashable.
                pass
            else:
                if not exp_set:
                    return 1.0 if not act_set else 0.0
                return len(exp_set & act_set) / len(exp_set)
        if len(expected) != len(actual):
            return 0.0
        scores = [self._compare(e, a) for e, a in zip(expected, actual, strict=False)]
        return sum(scores) / len(scores)

    def _canon(self, v: Any) -> Any:
        if isinstance(v, str):
            x = v.strip() if self._strip else v
            return x.lower() if not self._case_sensitive else x
        return v
