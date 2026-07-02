# How the three recommendations are computed

The Decision UI's headline panel shows three picks per run with the math in
plain view. No black-box recommendation. Same logic in the Markdown report
and console reporter.

## Max Accuracy

```python
sorted(rows, key=lambda r: (-r.score_mean, r.total_cost_usd))[0]
```

Highest mean score. Ties broken by lower total cost.

## Best Price/Performance

How the pick is made:

1. **Filter:** keep only models with `score_mean ≥ threshold` (default
   `0.80`). The UI shows excluded models with their score, so it's never
   silent.
2. **Rank by cost-per-accuracy-point:**
   `total_cost_usd / (score_mean * 100)`.
3. **Tie-break** on higher `score_mean`.

For a worked example, see the leaderboard rendered into the Markdown
report — the rationale string contains the actual numbers.

## Lowest Cost

```python
sorted(rows, key=lambda r: (r.total_cost_usd, -r.score_mean))[0]
```

Cheapest model, no accuracy filter. Tie-break on higher score.

## Why not a single composite score

Composite scores hide the trade-off. Three side-by-side cards force the
user to choose between accuracy, cost-effectiveness, and raw cost — the
choice is theirs to make, not the tool's to obscure.

The Markdown and console reporters print the math the same way the UI
renders it. The exact filter threshold (default `0.80`) is configurable per
call to the recommendations API.
