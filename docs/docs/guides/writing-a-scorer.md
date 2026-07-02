# Writing a custom scorer

Scorers are the quickest extension point. A scorer is any class that
implements the [`Scorer`](../api.md#clean_evals.Scorer) protocol — no base
class to inherit, no decorator.

## Skeleton

```python
from typing import Any, ClassVar
from clean_evals import Case, ModelResponse, ScoreResult

class LevenshteinScorer:
    name: ClassVar[str] = "levenshtein"

    def __init__(self, *, threshold: float = 0.8) -> None:
        self._threshold = threshold

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LevenshteinScorer":
        return cls(threshold=float(config.get("threshold", 0.8)))

    def score(self, case: Case, response: ModelResponse) -> ScoreResult:
        from rapidfuzz.distance import Levenshtein
        expected = (case.expected or {}).get("text", "")
        ratio = Levenshtein.normalized_similarity(expected, response.content)
        return ScoreResult(
            score=ratio, passed=ratio >= self._threshold,
            breakdown={"ratio": ratio},
        )
```

## Registration

In your `pyproject.toml`:

```toml
[project.entry-points."clean_evals.scorers"]
levenshtein = "my_pkg.scorers:LevenshteinScorer"
```

Install with `pip install -e .` and `clean-evals list-scorers` will show
`levenshtein` alongside the built-ins.

## Determinism

Scorers should be **pure**: same `(case, response)` always yields the same
`ScoreResult`. Anything stochastic — LLM judges, sampling — should be
seeded.
