"""Console reporter — Rich-formatted table to stdout.

Writes nothing to disk. Returns ``output_dir`` as the "primary artifact"
path so the reporter protocol contract is satisfied.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from clean_evals._internal.recommendations import all_three
from clean_evals.models import RunResult


class ConsoleReporter:
    name: ClassVar[str] = "console"

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def write(self, result: RunResult, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        self._render(result)
        return output_dir

    def _render(self, result: RunResult) -> None:
        c = self._console
        c.rule(f"[bold]clean-evals · {result.dataset} {result.dataset_version}[/bold]")

        table = Table(box=box.SIMPLE_HEAVY)
        table.add_column("Model")
        table.add_column("Score", justify="right")
        table.add_column("Pass", justify="right")
        table.add_column("p95 lat", justify="right")
        table.add_column("Errors", justify="right")
        table.add_column("$/run", justify="right")
        table.add_column("$/correct", justify="right")

        for s in result.summary.values():
            cpc = f"${s.cost_per_correct_usd:.4f}" if s.cost_per_correct_usd is not None else "—"
            table.add_row(
                s.model,
                f"{s.score_mean:.3f}",
                f"{s.cases_passed}/{s.cases_run}",
                f"{s.latency_p95_ms / 1000:.1f}s",
                str(int(s.error_rate * s.cases_run)),
                f"${s.total_cost_usd:.3f}",
                cpc,
            )
        c.print(table)

        recs = all_three(result)
        body = "\n".join(
            (
                f"[bold]Max Accuracy:[/bold]            {recs['max_accuracy'].rationale}",
                f"[bold]Best Price/Performance:[/bold]  {recs['price_performance'].rationale}",
                f"[bold]Lowest Cost:[/bold]             {recs['lowest_cost'].rationale}",
            )
        )
        c.print(Panel(body, title="Recommendations", expand=True))

        if not result.deterministic:
            c.print(
                "[yellow]Non-deterministic run (temperature > 0). "
                "Re-runs may produce different scores.[/yellow]"
            )
        if result.notes:
            c.print("\n[bold]Notes[/bold]")
            for n in result.notes:
                c.print(f"  - {n}")

        c.rule("[dim]clean-evals · by datathere · github.com/datathere/clean-evals[/dim]")
