# Reporters

Reporters write a `RunResult` to a destination. Four ship in-tree:

| Name       | Output                                          | Purpose                  |
| ---------- | ----------------------------------------------- | ------------------------ |
| `markdown` | `run_<id>.md` (humans, PRs)                     | Primary human artifact   |
| `jsonl`    | `run_<id>.jsonl` (one row per `(case, model)`)   | CI scripts, dashboards   |
| `junit`    | `run_<id>.junit.xml`                            | CI test reporters        |
| `console`  | Rich-formatted table to stdout                  | Local terminal use       |

## JSONL schema (stable)

```jsonl
{"run_id":"r_018f...","case_id":"case_001","model":"claude-3-5-sonnet-20241022",
 "status":"ok","score":1.0,"passed":true,"latency_ms":3812,
 "tokens_in":2104,"tokens_out":312,"cost_usd":0.0094,
 "pricing_version":"2026.04",
 "started_at":"2026-04-29T10:00:00Z","finished_at":"2026-04-29T10:00:04Z"}
```

Adding fields ratchets a minor version; renaming or removing fields ratchets
a major.

## Per-case diff

When a case fails, a `case_<id>__<model>.diff.md` lands next to the run
artifacts with the prompt sent, the expected vs actual, and the scorer
breakdown.
