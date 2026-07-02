"""Built-in scorers.

Three are shipped in-tree:

- :class:`~clean_evals.scorers.exact_match.ExactMatchScorer` — string equality.
- :class:`~clean_evals.scorers.json_field_match.JsonFieldMatchScorer` —
  per-field equality for structured outputs.
- :class:`~clean_evals.scorers.llm_judge.LLMJudgeScorer` — Claude Haiku
  rubric-style judge.

Anything domain-specific belongs in your own package. Register via the
``clean_evals.scorers`` entry-point group.
"""

from __future__ import annotations

from clean_evals.scorers.exact_match import ExactMatchScorer
from clean_evals.scorers.json_field_match import JsonFieldMatchScorer
from clean_evals.scorers.llm_judge import LLMJudgeScorer

__all__ = ["ExactMatchScorer", "JsonFieldMatchScorer", "LLMJudgeScorer"]
