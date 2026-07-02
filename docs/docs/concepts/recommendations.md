# How the three recommendations are computed

The Decision UI shows three recommendations per run, each with the numbers
used to compute it. The Markdown report and console reporter apply the
same logic.

## Max Accuracy

```python
sorted(rows, key=lambda r: (-r.score_mean, r.total_cost_usd))[0]
```

Highest mean score. Ties broken by lower total cost.

## Best Price/Performance

How the pick is made:

1. **Filter:** keep only models with `score_mean ≥ threshold` (default
   `0.80`). The UI lists excluded models with their scores.
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

## Why three recommendations rather than one composite score

A composite score collapses the accuracy/cost trade-off into a single
number. Three cards keep the trade-off explicit: you choose which
dimension matters for your use case.

The Markdown and console reporters print the same numbers the UI renders.
The filter threshold (default `0.80`) is configurable per call to the
recommendations API.
