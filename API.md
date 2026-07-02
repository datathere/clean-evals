# clean-evals — Public API stability

The public API is everything imported from `clean_evals`. Anything under
`clean_evals._internal` may change without notice between minor versions.

This document is the contract. SemVer applies. Breaking changes ratchet a
major. Pre-1.0, minor versions may break the public API with a
`CHANGELOG.md` entry.

## Stability tags

| Tag      | Meaning                                                       |
| -------- | ------------------------------------------------------------- |
| stable   | Won't change without a major bump                             |
| beta     | May change at minor bumps with a `DeprecationWarning` notice  |

| Symbol                              | Tag    |
| ----------------------------------- | ------ |
| `clean_evals.Case`                  | stable |
| `clean_evals.Dataset`               | stable |
| `clean_evals.ModelResponse`         | stable |
| `clean_evals.ScoreResult`           | stable |
| `clean_evals.CaseResult`            | stable |
| `clean_evals.RunConfig`             | stable |
| `clean_evals.ModelSummary`          | stable |
| `clean_evals.RunResult`             | stable |
| `clean_evals.Runner`                | stable |
| `clean_evals.Scorer`                | stable |
| `clean_evals.ModelAdapter`          | stable |
| `clean_evals.Reporter`              | stable |
| `clean_evals.Scrubber`              | stable |
| `clean_evals.runner.Runner.run`     | stable |
| `clean_evals.runner.Runner.run_sync`| stable |
| `clean_evals.Dataset.from_yaml`     | stable |
| `clean_evals.Dataset.to_yaml`       | beta   |
| `clean_evals.errors.*`              | stable |
| Module `clean_evals.pricing`        | stable |
| Module `clean_evals.registry`       | stable |
| Module `clean_evals.adapters.*`     | stable |
| Module `clean_evals.scorers.*`      | stable |
| Module `clean_evals.reporters.*`    | stable |
| `clean_evals.web` REST endpoints    | beta   |
| `clean_evals.queue.tasks.run_eval`  | beta   |

## Adding fields

Adding optional fields to the public Pydantic models is a minor bump.
Removing or renaming fields, or changing field types, is a major bump.

## Removing modules

Anything in `clean_evals._internal` may be removed at any time.

## Backwards-compatible changes (non-breaking)

- Adding new scorers / adapters / reporters in-tree.
- Adding new CLI subcommands.
- Adding new optional `RunConfig` fields with defaults.
- Adding new `clean_evals.errors.*` exception types that don't replace
  existing ones.
