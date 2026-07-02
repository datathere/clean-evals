"""Markdown report — the human-facing primary artifact.

Produces ``run_<run_id>.md`` plus per-case diff files for every failed or
errored case. The Markdown reads cleanly when pasted into a PR description.

Footer attribution is hardcoded — see BRANDING.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from clean_evals._internal.recommendations import all_three
from clean_evals.models import RunResult

_FOOTER = "\n\n---\n\n_clean-evals · by datathere · github.com/datathere/clean-evals_\n"


class MarkdownReporter:
    name: ClassVar[str] = "markdown"

    def write(self, result: RunResult, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"run_{result.run_id}.md"
        path.write_text(_render(result), encoding="utf-8")
        return path


def _render(result: RunResult) -> str:
    cfg = result.config
    rows: list[str] = []
    for model, s in result.summary.items():
        cost_per_correct = (
            f"${s.cost_per_correct_usd:.4f}" if s.cost_per_correct_usd is not None else "n/a"
        )
        rows.append(
            f"| {model} | {s.score_mean:.3f} | {s.cases_passed}/{s.cases_run} | "
            f"{s.latency_p95_ms / 1000:.1f}s | {int(s.error_rate * s.cases_run)} | "
            f"${s.total_cost_usd:.3f} | {cost_per_correct} |"
        )

    recs = all_three(result)
    pp = recs["price_performance"]
    rec_lines = [
        f"- **Max Accuracy:**           {recs['max_accuracy'].rationale}",
        f"- **Best Price/Performance:** {pp.rationale}",
        f"- **Lowest Cost:**            {recs['lowest_cost'].rationale}",
    ]

    notes_block = ""
    if result.notes:
        notes_block = "\n## Notes\n\n" + "\n".join(f"- {n}" for n in result.notes) + "\n"

    determinism_block = (
        ""
        if result.deterministic
        else "\n> ⚠ Non-deterministic run (temperature > 0). Re-runs may produce different scores.\n"
    )

    leaderboard = (
        "| Model | Score | Pass | p95 lat | Errors | $/run | $/correct |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |\n" + "\n".join(rows)
    )

    return (
        f"# clean-evals run · {result.dataset}\n\n"
        f"**Run id:** `{result.run_id}`\n\n"
        f"**Dataset:** {result.dataset} `{result.dataset_version}` · "
        f"{len(result.cases) // max(1, len(cfg.models))} cases · "
        f"models: {', '.join(cfg.models)}\n\n"
        f"**Config:** seed={cfg.seed}, temperature={cfg.temperature}, "
        f"pricing_version={result.pricing_version}\n"
        f"{determinism_block}\n"
        f"## Leaderboard\n\n{leaderboard}\n\n"
        f"## Recommendations\n\n" + "\n".join(rec_lines) + "\n" + notes_block + _FOOTER
    )
