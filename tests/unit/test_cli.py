"""Smoke tests for the CLI surface."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from clean_evals.cli import app

_runner = CliRunner()


def test_version_flag() -> None:
    result = _runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "clean-evals" in result.stdout


def test_list_scorers() -> None:
    result = _runner.invoke(app, ["list-scorers"])
    assert result.exit_code == 0
    assert "exact_match" in result.stdout


def test_list_adapters() -> None:
    result = _runner.invoke(app, ["list-adapters"])
    assert result.exit_code == 0
    assert "anthropic" in result.stdout


def test_list_reporters() -> None:
    result = _runner.invoke(app, ["list-reporters"])
    assert result.exit_code == 0
    assert "markdown" in result.stdout


def test_list_models() -> None:
    result = _runner.invoke(app, ["list-models"])
    assert result.exit_code == 0
    assert "anthropic" in result.stdout


def test_run_with_invalid_dataset(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text(
        yaml.safe_dump({"name": "d", "version": "v1", "scorer": "s", "unknown": True}),
        encoding="utf-8",
    )
    result = _runner.invoke(
        app,
        ["run", str(bad), "--models", "claude-3-5-sonnet-20241022", "--max-cost", "1"],
    )
    assert result.exit_code == 3  # EXIT_CONFIG_INVALID
