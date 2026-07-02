"""The three side-by-side recommendations.

The Decision UI shows three picks per run with the math in plain view:

- **Max Accuracy** — highest ``score_mean`` regardless of cost.
- **Best Price/Performance** — among models with ``score_mean`` >= a threshold,
  lowest ``total_cost_usd / (score_mean * 100)`` (cost per accuracy point).
- **Lowest Cost** — cheapest run, no accuracy filter.

Each function returns a ``Recommendation`` with the chosen model, its summary
row, and a ``rationale`` string the UI renders verbatim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from clean_evals.models import ModelSummary, RunResult

DEFAULT_PP_THRESHOLD = 0.80


def fmt_usd(value: float) -> str:
    """Format a USD amount without flattening small values to $0.000.

    Cheap models cost fractions of a millicent per run; fixed 3-decimal
    formatting renders them all as $0.000 and the comparison math becomes
    unreadable. Keep two significant digits for sub-cent values instead.
    """
    if value == 0:
        return "$0"
    if abs(value) >= 0.01:
        return f"${value:.2f}"
    decimals = 1 - math.floor(math.log10(abs(value)))
    return f"${value:.{decimals}f}"


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Single recommendation card payload."""

    kind: str  # "max_accuracy" | "price_performance" | "lowest_cost"
    model: str | None
    summary: ModelSummary | None
    rationale: str


def max_accuracy(result: RunResult) -> Recommendation:
    """Highest ``score_mean``. Ties broken by lower ``total_cost_usd``."""
    rows = list(result.summary.values())
    if not rows:
        return Recommendation("max_accuracy", None, None, "No model results available.")
    rows.sort(key=lambda r: (-r.score_mean, r.total_cost_usd))
    top = rows[0]
    return Recommendation(
        kind="max_accuracy",
        model=top.model,
        summary=top,
        rationale=f"{top.model} — {top.score_mean:.3f} mean score.",
    )


def price_performance(
    result: RunResult,
    *,
    threshold: float = DEFAULT_PP_THRESHOLD,
) -> Recommendation:
    """Best cost-per-accuracy-point among models >= ``threshold`` ``score_mean``."""
    qualifying = [r for r in result.summary.values() if r.score_mean >= threshold]
    excluded = [r for r in result.summary.values() if r.score_mean < threshold]

    if not qualifying:
        excluded_summary = ", ".join(
            f"{r.model} ({r.score_mean:.1%})" for r in sorted(excluded, key=lambda r: r.model)
        )
        return Recommendation(
            kind="price_performance",
            model=None,
            summary=None,
            rationale=(
                f"No models met the {threshold:.0%} accuracy threshold. "
                f"Below threshold: {excluded_summary or 'none'}."
            ),
        )

    def cost_per_pt(r: ModelSummary) -> float:
        denom = r.score_mean * 100.0
        return r.total_cost_usd / denom if denom > 0 else float("inf")

    qualifying.sort(key=lambda r: (cost_per_pt(r), -r.score_mean))
    top = qualifying[0]

    breakdown_pieces = [
        f"{r.model} {fmt_usd(r.total_cost_usd)} / {r.score_mean * 100:.1f}"
        f" = {fmt_usd(cost_per_pt(r))}/pt"
        for r in qualifying
    ]
    excluded_pieces = [f"{r.model} ({r.score_mean:.1%})" for r in excluded]
    excluded_text = f" Below threshold: {', '.join(excluded_pieces)}." if excluded_pieces else ""
    rationale = (
        f"Filter applied: >={threshold:.0%} accuracy.{excluded_text} "
        f"Among qualifiers: {' vs '.join(breakdown_pieces)} -> {top.model} wins on "
        f"cost-per-accuracy-point."
    )
    return Recommendation(
        kind="price_performance", model=top.model, summary=top, rationale=rationale
    )


def lowest_cost(result: RunResult) -> Recommendation:
    """Cheapest model, no accuracy filter."""
    rows = list(result.summary.values())
    if not rows:
        return Recommendation("lowest_cost", None, None, "No model results available.")
    rows.sort(key=lambda r: (r.total_cost_usd, -r.score_mean))
    top = rows[0]
    return Recommendation(
        kind="lowest_cost",
        model=top.model,
        summary=top,
        rationale=f"{top.model} — {fmt_usd(top.total_cost_usd)} per run.",
    )


def all_three(
    result: RunResult, *, threshold: float = DEFAULT_PP_THRESHOLD
) -> dict[str, Recommendation]:
    """Convenience: compute all three recommendations in one call."""
    return {
        "max_accuracy": max_accuracy(result),
        "price_performance": price_performance(result, threshold=threshold),
        "lowest_cost": lowest_cost(result),
    }
