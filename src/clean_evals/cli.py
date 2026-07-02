"""``clean-evals`` command-line interface.

Documented exit codes:

- ``0`` — success.
- ``1`` — regression detected against ``--baseline``.
- ``2`` — score below ``--fail-on-score`` threshold.
- ``3`` — config invalid.
- ``4`` — cost ceiling hit.
- ``64–78`` — standard sysexits (``EX_USAGE``, ``EX_DATAERR``, …) for
  unforeseen failures.

Subcommands map 1:1 to the proposal's CLI surface. Implementation uses
Typer because it's compact and produces good ``--help`` output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from clean_evals._internal.recommendations import all_three
from clean_evals._internal.version import __version__
from clean_evals.errors import (
    CleanEvalsError,
    ConfigError,
    CostCeilingExceeded,
    DailyCostLimitExceeded,
    UnknownPlugin,
)
from clean_evals.models import Dataset, RunConfig

app = typer.Typer(
    name="clean-evals",
    help="Try out your prompts and context across AI models. Run evals and find the best model for your use case.",
    add_completion=False,
    no_args_is_help=True,
)

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_BELOW_THRESHOLD = 2
EXIT_CONFIG_INVALID = 3
EXIT_COST_CEILING = 4

_console = Console()


# ---------------------------------------------------------------------------
# Top-level / version
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"clean-evals {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[  # noqa: ARG001 — consumed by the eager callback
        bool,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True),
    ] = False,
) -> None:
    """clean-evals · by datathere · github.com/datathere/clean-evals"""
    # Self-hosted installs keep provider keys in .env (see .env.example).
    # Real environment variables win over the file.
    from dotenv import load_dotenv

    load_dotenv(override=False)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


@app.command()
def run(
    dataset_path: Annotated[Path, typer.Argument(exists=True, readable=True)],
    models: Annotated[str, typer.Option("--models", "-m", help="Comma-separated model snapshots")],
    timeout: Annotated[float, typer.Option("--timeout", help="Per-call timeout, seconds")] = 120.0,
    seed: Annotated[int, typer.Option("--seed")] = 42,
    temperature: Annotated[float, typer.Option("--temperature")] = 0.0,
    max_cost: Annotated[float, typer.Option("--max-cost", help="USD")] = 5.0,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("./results"),
    reporters: Annotated[
        str,
        typer.Option(
            "--reporters",
            help="Comma-separated reporter names (markdown, jsonl, junit, console)",
        ),
    ] = "markdown,jsonl,console",
    baseline: Annotated[
        str | None, typer.Option("--baseline", help="Compare against a prior run id")
    ] = None,
    fail_on_regression: Annotated[bool, typer.Option("--fail-on-regression")] = False,
    fail_on_score: Annotated[
        float | None, typer.Option("--fail-on-score", help="Min mean score required")
    ] = None,
    persist: Annotated[
        bool, typer.Option("--persist/--no-persist", help="Store results in DB")
    ] = False,
) -> None:
    """Run an eval over a dataset YAML."""
    from clean_evals.runner import Runner

    try:
        ds = Dataset.from_yaml(dataset_path)
    except Exception as exc:
        _console.print(f"[red]Dataset load failed:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG_INVALID) from exc

    try:
        cfg = RunConfig(
            models=[m.strip() for m in models.split(",") if m.strip()],
            timeout_s=timeout,
            seed=seed,
            temperature=temperature,
            max_cost_usd=max_cost,
        )
    except Exception as exc:
        _console.print(f"[red]Config invalid:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG_INVALID) from exc

    # The daily cost limit compares against persisted history. Look it up
    # when the limit is set; without storage the check degrades to $0.
    import os

    daily_spend: float | None = None
    if os.environ.get("CLEAN_EVALS_DAILY_COST_LIMIT_USD"):
        try:
            from clean_evals.storage.db import session_factory
            from clean_evals.storage.repo import spend_today

            with session_factory()() as session:
                daily_spend = spend_today(session)
        except Exception as exc:
            _console.print(
                f"[yellow]Could not read today's spend from storage ({exc}); "
                "the daily limit is checked against $0.00 for this run.[/yellow]"
            )

    try:
        result = Runner(daily_cost_so_far_usd=daily_spend).run_sync(ds, cfg)
    except DailyCostLimitExceeded as exc:
        _console.print(f"[red]Daily cost limit reached:[/red] {exc}")
        raise typer.Exit(EXIT_COST_CEILING) from exc
    except CostCeilingExceeded as exc:
        _console.print(f"[red]Per-run cost ceiling exceeded:[/red] {exc}")
        raise typer.Exit(EXIT_COST_CEILING) from exc
    except UnknownPlugin as exc:
        _console.print(f"[red]Plugin error:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG_INVALID) from exc

    output.mkdir(parents=True, exist_ok=True)
    primary: Path | None = None
    for r_name in [r.strip() for r in reporters.split(",") if r.strip()]:
        try:
            cls = _registry_get_reporter(r_name)
        except UnknownPlugin as exc:
            _console.print(f"[red]Unknown reporter {r_name!r}:[/red] {exc}")
            raise typer.Exit(EXIT_CONFIG_INVALID) from exc
        primary = cls().write(result, output)

    # Per-case diff for failures.
    from clean_evals.reporters.diff import write_case_diff

    diff_dir = output / "diffs"
    case_by_id = {c.id: c for c in ds.cases}
    for cr in result.cases:
        if (cr.score is not None and not cr.score.passed) or cr.status != "ok":
            case = case_by_id.get(cr.case_id)
            if case is None:
                continue
            write_case_diff(case, cr, diff_dir)

    # Optional persist
    if persist:
        from clean_evals.storage.db import session_factory
        from clean_evals.storage.repo import persist_run, upsert_dataset

        factory = session_factory()
        with factory() as session:
            upsert_dataset(session, ds)
            persist_run(
                session, result=result, artifact_uri=str(output.resolve()), triggered_by="cli"
            )
            session.commit()

    # Exit code policy
    if fail_on_score is not None:
        for s in result.summary.values():
            if s.score_mean < fail_on_score:
                _console.print(
                    f"[red]Score {s.score_mean:.3f} below threshold {fail_on_score:.3f}[/red]"
                )
                raise typer.Exit(EXIT_BELOW_THRESHOLD)
    if (
        baseline is not None
        and fail_on_regression
        and _is_regression_against_baseline(result, baseline)
    ):
        _console.print("[red]Regression detected against baseline[/red]")
        raise typer.Exit(EXIT_REGRESSION)

    if primary is not None:
        _console.print(f"[green]Primary report:[/green] {primary}")
    raise typer.Exit(EXIT_OK)


# ---------------------------------------------------------------------------
# Build (Dataset Builder entry from CLI)
# ---------------------------------------------------------------------------


@app.command()
def build(
    inputs: Annotated[Path, typer.Argument(exists=True, readable=True)],
    name: Annotated[str, typer.Option("--name", help="Dataset name")],
    version: Annotated[str, typer.Option("--version")] = "v1",
    scorer: Annotated[str, typer.Option("--scorer")] = "json_field_match",
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8080,
) -> None:
    """Open the Dataset Builder UI seeded with ``inputs``.

    Uploads inputs into a fresh in-progress dataset row, then starts the
    web server with a ?builder=<dataset_id> deep link.
    """
    from clean_evals.web.builder import seed_in_progress_dataset

    try:
        dataset_id = seed_in_progress_dataset(inputs, name=name, version=version, scorer=scorer)
    except ConfigError as exc:
        _console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_CONFIG_INVALID) from exc

    _console.print(
        f"[green]Seeded dataset id={dataset_id}.[/green] Opening builder at "
        f"http://{host}:{port}/builder/{dataset_id}"
    )
    serve(host=host, port=port)


@app.command()
def generate(
    dataset_id: Annotated[int, typer.Argument(help="Dataset id (see the Datasets page or API)")],
    models: Annotated[str, typer.Option("--models", "-m", help="Comma-separated model snapshots")],
    max_cost: Annotated[float, typer.Option("--max-cost", help="USD ceiling")] = 5.0,
    temperature: Annotated[float, typer.Option("--temperature")] = 0.0,
) -> None:
    """Generate one candidate output per case and model.

    Outputs are not scored. Review and rate them in the Dataset Builder.
    """
    import asyncio as _asyncio

    from clean_evals.candidates import generate_candidates
    from clean_evals.storage.db import session_factory

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    try:
        job = _asyncio.run(
            generate_candidates(
                session_factory(),
                dataset_id,
                model_list,
                temperature=temperature,
                max_cost_usd=max_cost,
            )
        )
    except ValueError as exc:
        _console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_CONFIG_INVALID) from exc
    color = "green" if job.status == "done" else "red"
    _console.print(
        f"[{color}]{job.status}[/{color}] — {job.done}/{job.total} outputs, "
        f"{job.errors} errors, ${job.cost_usd:.4f} spent."
    )
    if job.status == "aborted_cost":
        raise typer.Exit(EXIT_COST_CEILING)
    _console.print(f"Review and rate: http://127.0.0.1:8080/builder/{dataset_id}")


@app.command()
def calibrate(
    dataset_id: Annotated[int, typer.Argument(help="Dataset id")],
    judge_model: Annotated[
        str, typer.Option("--judge", help="Judge model snapshot")
    ] = "claude-haiku-4-5-20251001",
) -> None:
    """Calibrate the LLM judge against your ratings.

    Requires rated candidate outputs. Prints the agreement numbers and
    stores a new judge configuration version.
    """
    import asyncio as _asyncio

    from clean_evals.calibration import calibrate as _calibrate
    from clean_evals.storage.db import session_factory

    try:
        config = _asyncio.run(_calibrate(session_factory(), dataset_id, judge_model=judge_model))
    except ValueError as exc:
        _console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_CONFIG_INVALID) from exc

    summary = config.agreement_jsonb.get("summary", {})
    table = Table(title=f"Judge agreement — v{config.version} ({config.judge_model})")
    table.add_column("n")
    table.add_column("exact")
    table.add_column("within +/-1")
    table.add_column("kappa")
    table.add_row(
        str(summary.get("n", 0)),
        f"{summary.get('exact', 0.0):.0%}",
        f"{summary.get('within_one', 0.0):.0%}",
        f"{summary.get('kappa', 0.0):.2f}",
    )
    _console.print(table)
    kappa = float(summary.get("kappa", 0.0))
    if kappa < 0.6:
        _console.print(
            "[yellow]Kappa is below 0.6. Add feedback on the cases where the judge "
            "disagrees with your ratings, then calibrate again.[/yellow]"
        )


# ---------------------------------------------------------------------------
# Show / diff
# ---------------------------------------------------------------------------


@app.command()
def show(run_id: Annotated[str, typer.Argument()]) -> None:
    """Show a stored run's leaderboard + recommendations."""
    from clean_evals.storage.db import session_factory
    from clean_evals.storage.repo import hydrate_run

    factory = session_factory()
    with factory() as session:
        result = hydrate_run(session, run_id)
    if result is None:
        _console.print(f"[red]Run {run_id!r} not found[/red]")
        raise typer.Exit(EXIT_CONFIG_INVALID)

    table = Table(title=f"Run {result.run_id}")
    table.add_column("Model")
    table.add_column("Score", justify="right")
    table.add_column("Pass", justify="right")
    table.add_column("$/run", justify="right")
    for s in result.summary.values():
        table.add_row(
            s.model,
            f"{s.score_mean:.3f}",
            f"{s.cases_passed}/{s.cases_run}",
            f"${s.total_cost_usd:.3f}",
        )
    _console.print(table)
    recs = all_three(result)
    _console.print(
        f"\n[bold]Max accuracy:[/bold] {recs['max_accuracy'].rationale}\n"
        f"[bold]Best price/perf:[/bold] {recs['price_performance'].rationale}\n"
        f"[bold]Lowest cost:[/bold] {recs['lowest_cost'].rationale}"
    )


@app.command()
def diff(run_a: Annotated[str, typer.Argument()], run_b: Annotated[str, typer.Argument()]) -> None:
    """Compare two runs by per-model mean score and total cost."""
    from clean_evals.storage.db import session_factory
    from clean_evals.storage.repo import hydrate_run

    factory = session_factory()
    with factory() as session:
        a = hydrate_run(session, run_a)
        b = hydrate_run(session, run_b)
    if a is None or b is None:
        _console.print("[red]One or both runs not found[/red]")
        raise typer.Exit(EXIT_CONFIG_INVALID)
    table = Table(title=f"{run_a} vs {run_b}")
    table.add_column("Model")
    table.add_column("Δ Score", justify="right")
    table.add_column("Δ Cost", justify="right")
    models = sorted(set(a.summary) | set(b.summary))
    for m in models:
        sa, sb = a.summary.get(m), b.summary.get(m)
        if sa is None or sb is None:
            table.add_row(m, "—", "—")
            continue
        table.add_row(
            m,
            f"{sb.score_mean - sa.score_mean:+.3f}",
            f"{sb.total_cost_usd - sa.total_cost_usd:+.3f}",
        )
    _console.print(table)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@app.command(name="list-scorers")
def list_scorers() -> None:
    """List registered scorers."""
    from clean_evals.registry import scorers

    for n in scorers.names():
        typer.echo(n)


@app.command(name="list-adapters")
def list_adapters() -> None:
    """List registered adapters."""
    from clean_evals.registry import adapters

    for n in adapters.names():
        typer.echo(n)


@app.command(name="list-reporters")
def list_reporters() -> None:
    """List registered reporters."""
    from clean_evals.registry import reporters

    for n in reporters.names():
        typer.echo(n)


@app.command(name="list-models")
def list_models() -> None:
    """List models present in the bundled pricing table."""
    from clean_evals.pricing import known_models

    for provider, model in known_models():
        typer.echo(f"{provider}\t{model}")


# ---------------------------------------------------------------------------
# Migrate
# ---------------------------------------------------------------------------


@app.command()
def migrate(
    revision: Annotated[str, typer.Option("--revision")] = "head",
) -> None:
    """Apply Alembic migrations against ``CLEAN_EVALS_DATABASE_URL``."""
    from clean_evals.storage.migrations.runner import upgrade

    try:
        upgrade(revision)
    except CleanEvalsError as exc:
        _console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_CONFIG_INVALID) from exc
    except Exception as exc:  # Alembic raises its own exception types.
        _console.print(f"[red]Migration failed: {exc}[/red]")
        raise typer.Exit(EXIT_CONFIG_INVALID) from exc
    _console.print(f"[green]Migrated to {revision}[/green]")


# ---------------------------------------------------------------------------
# Worker / Beat / Serve
# ---------------------------------------------------------------------------


@app.command()
def worker(
    concurrency: Annotated[int, typer.Option("--concurrency", "-c")] = 2,
    loglevel: Annotated[str, typer.Option("--loglevel")] = "INFO",
) -> None:
    """Start a Celery worker."""
    from clean_evals.queue.app import app as celery_app

    argv = [
        "worker",
        f"--concurrency={concurrency}",
        f"--loglevel={loglevel}",
        "-n",
        "clean-evals-worker@%h",
    ]
    celery_app.worker_main(argv=argv)


@app.command()
def beat(
    loglevel: Annotated[str, typer.Option("--loglevel")] = "INFO",
) -> None:
    """Start the Celery Beat scheduler with the DB-backed schedule."""
    from clean_evals.queue.app import app as celery_app
    from clean_evals.queue.schedule import install_schedule

    install_schedule()
    celery_app.start(argv=["beat", f"--loglevel={loglevel}"])


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8080,
    reload: Annotated[bool, typer.Option("--reload")] = False,
) -> None:
    """Start the FastAPI web UI."""
    import os

    import uvicorn

    if host not in {"127.0.0.1", "localhost"} and not _user_acked_remote_bind():
        _console.print(
            "[yellow]Binding to a non-loopback address. clean-evals has no auth.[/yellow]"
        )
    # Seed the sample dataset on a pristine database. No-op otherwise.
    try:
        from clean_evals.starter import seed_starter_dataset
        from clean_evals.storage.db import session_factory

        with session_factory()() as session:
            seeded = seed_starter_dataset(session)
        if seeded is not None:
            _console.print(f"[green]Created the sample dataset (id={seeded}).[/green]")
    except Exception as exc:
        _console.print(f"[yellow]Could not create the sample dataset: {exc}[/yellow]")
    uvicorn.run(
        "clean_evals.web.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level=os.environ.get("CLEAN_EVALS_LOG_LEVEL", "info").lower(),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry_get_reporter(name: str) -> type:
    from clean_evals.registry import reporters

    return reporters.get(name)


def _is_regression_against_baseline(result: Any, baseline_run_id: str) -> bool:
    from clean_evals.storage.db import session_factory
    from clean_evals.storage.repo import hydrate_run

    factory = session_factory()
    with factory() as session:
        baseline = hydrate_run(session, baseline_run_id)
    if baseline is None:
        return False
    for model, summary in result.summary.items():
        prev = baseline.summary.get(model)
        if prev is None:
            continue
        if summary.score_mean + 1e-9 < prev.score_mean:
            return True
    return False


def _user_acked_remote_bind() -> bool:
    import os

    return os.environ.get("CLEAN_EVALS_ACK_REMOTE_BIND") == "1"


# Allow ``python -m clean_evals.cli``
if __name__ == "__main__":  # pragma: no cover
    app()
