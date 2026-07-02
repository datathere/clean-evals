# Scorers

Scorers compute a 0.0–1.0 quality score for a model's response on a single
case. The `Scorer` protocol is small:

```python
class Scorer(Protocol):
    name: ClassVar[str]
    def score(self, case: Case, response: ModelResponse) -> ScoreResult: ...
    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Scorer": ...
```

Implementations should be pure: same `(case, response)` always yields the
same `ScoreResult`. Anything stochastic (LLM judges) should be seeded so the
run is reproducible.

## Built-ins

| Name               | Purpose                                       |
| ------------------ | --------------------------------------------- |
| `exact_match`      | String equality with optional case/strip      |
| `json_field_match` | Per-field equality with optional weights      |
| `llm_judge`        | Claude Haiku rubric-style judge               |

See [Writing a scorer](../guides/writing-a-scorer.md) for the full guide.
