# Cost ceilings

Two limits bound spending during eval runs. Both are **best-effort
estimates**, computed from the bundled pricing snapshot rather than
provider billing data. Always verify actual spend in your model provider's
billing console.

## Per-run limit

```yaml
# In RunConfig (CLI: --max-cost)
max_cost_usd: 5.0
```

The runner checks cumulative cost as results arrive. Cases that have not
started when the ceiling trips are aborted with `status="aborted_cost"` and
whatever results already exist are persisted. Calls that are already in
flight complete, so the final spend can overshoot the ceiling — by more when
concurrency is high. Set explicit per-provider `concurrency` caps to bound
the overshoot.

## Daily safety net (optional)

```bash
export CLEAN_EVALS_DAILY_COST_LIMIT_USD=25
```

The runner refuses to start a new run if today's cumulative spend already
meets this limit. It compares against
`SUM(case_results.cost_usd) WHERE started_at >= today` — that is,
**persisted runs only**: web runs, scheduled runs, and CLI runs with
`--persist`. A CLI run without `--persist` spends money but leaves no cost
trail, so it is invisible to this check.

This is a **start-of-run** check, not mid-run — once a run is under way,
the per-run `max_cost_usd` takes over.

## What's not provided

- **No spend guarantee.** Both limits are estimates from the pricing table;
  provider-side price changes or untracked runs mean real spend can differ.
- **No retry loops without backoff.** All adapter retries use exponential
  backoff with jitter, plus `Retry-After` honour (capped at 120 seconds).
- **Concurrency caps are explicit.** By default the runner issues requests
  as fast as the provider allows and backs off on 429s. Set per-provider
  caps when the API key is shared with other consumers:

```yaml
concurrency:
  anthropic: 5
  openai: 10
```

## Surfacing judge cost

When using `llm_judge` against a large dataset, the judge cost can rival
the candidate-model cost. Surface judge spend separately by tagging it in a
custom reporter, or rely on the run's `pricing_version` + `cost_usd`
columns to break it out post-hoc.
