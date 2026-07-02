"""Exact-string-match scorer.

Compares ``response.content`` (or a configured field) against
``case.expected``. The simplest scorer; useful for classification tasks
with constrained outputs.

Configuration:

.. code-block:: yaml

    scorer: exact_match
    scorer_config:
      field: label              # field of expected to compare against
      strip: true               # strip whitespace before comparing
      case_sensitive: false     # default false
      pass_threshold: 1.0       # exact match -> 1.0; otherwise 0.0
"""

from __future__ import annotations

from typing import Any, ClassVar

from clean_evals.models import Case, ModelResponse, ScoreResult


class ExactMatchScorer:
    name: ClassVar[str] = "exact_match"

    def __init__(
        self,
        *,
        field: str | None = None,
        strip: bool = True,
        case_sensitive: bool = False,
        pass_threshold: float = 1.0,
    ) -> None:
        self._field = field
        self._strip = strip
        self._case_sensitive = case_sensitive
        self._pass_threshold = pass_threshold

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ExactMatchScorer:
        return cls(
            field=config.get("field"),
            strip=bool(config.get("strip", True)),
            case_sensitive=bool(config.get("case_sensitive", False)),
            pass_threshold=float(config.get("pass_threshold", 1.0)),
        )

    def score(self, case: Case, response: ModelResponse) -> ScoreResult:
        expected_value: Any
        if case.expected is None:
            expected_value = ""
        elif self._field is not None:
            expected_value = case.expected.get(self._field, "")
        else:
            expected_value = case.expected.get("text") or case.expected.get("answer") or ""

        actual: str
        if self._field is not None and response.parsed is not None:
            actual = str(response.parsed.get(self._field, ""))
        else:
            actual = response.content

        a = str(expected_value)
        b = actual
        if self._strip:
            a = a.strip()
            b = b.strip()
        if not self._case_sensitive:
            a = a.lower()
            b = b.lower()

        score = 1.0 if a == b else 0.0
        return ScoreResult(
            score=score,
            passed=score >= self._pass_threshold,
            breakdown={"match": score},
            notes=None if score == 1.0 else f"expected={a!r}, got={b!r}",
        )
