# Datasets

A dataset is a `(name, version)`-keyed collection of `Case` rows plus its
scoring configuration. Datasets are immutable once tagged: edits bump the
version, and historical runs against `v1` remain comparable after `v2`
ships.

## YAML format

```yaml
name: sentiment
version: v1
description: Three-class sentiment classification.
scorer: exact_match
scorer_config:
  field: label
  case_sensitive: false
  prompt_template: |
    Classify ... {prompt}
cases:
  - id: pos_001
    input: { prompt: "I love it" }
    expected: { label: positive }
    tags: [happy-path]
```

Unknown top-level keys are errors, not warnings (`extra="forbid"` on
all Pydantic models).

## Sidecar JSONL

For datasets too large to inline, reference a JSONL sidecar:

```yaml
name: big_dataset
version: v1
scorer: json_field_match
cases_jsonl: ./cases.jsonl
```

`cases.jsonl` is one `Case` per line.

## Scoring

The `scorer` field names a scorer registered under the
`clean_evals.scorers` entry-point group. `scorer_config` is passed verbatim
to `Scorer.from_config`. Three scorers ship in-tree:

- `exact_match` — string equality with optional case/strip.
- `json_field_match` — per-field equality with optional weights.
- `llm_judge` — Claude Haiku rubric-style judge.

Anything domain-specific belongs in your own package.

## Locking semantics

A locked case is immutable. The `expected` field cannot change. Editing a
locked case is treated as a dataset-version bump (`v1` → `v2`). The Builder
UI enforces this; the CLI's `clean-evals run --persist` does too.
