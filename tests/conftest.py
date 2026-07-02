"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Strip provider keys / cost limits from the environment by default.

    Individual tests opt back in by setting them explicitly.
    The fixture yields without teardown — monkeypatch handles cleanup.
    """
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        # The CLI tests run the real entry point, which loads .env into the
        # process; without stripping these, a developer's local Ollama URL
        # makes probe tests hit a live server mid-suite.
        "CLEAN_EVALS_LOCAL_BASE_URL",
        "CLEAN_EVALS_LOCAL_API_KEY",
        "CLEAN_EVALS_DAILY_COST_LIMIT_USD",
        "CLEAN_EVALS_DATABASE_URL",
        "CLEAN_EVALS_ARTIFACT_STORE",
        "CLEAN_EVALS_ARTIFACT_DIR",
    ):
        monkeypatch.delenv(var, raising=False)
    # Point the data files at per-test temp paths. The defaults resolve
    # relative to the working directory, so tests run from a checkout would
    # otherwise read the developer's live pricing and exclusion files and
    # pass or fail on machine state.
    monkeypatch.setenv("CLEAN_EVALS_PRICING_FILE", str(tmp_path / "pricing.yml"))
    monkeypatch.setenv("CLEAN_EVALS_EXCLUDED_MODELS_FILE", str(tmp_path / "excluded-models.yml"))
    yield  # noqa: PT022 — pytest needs a yield-fixture for autouse setup-only


@pytest.fixture(autouse=True)
def _seed_model_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-fill the OpenRouter metadata cache so tests stay off the network.

    Tests that exercise the fetch reset ``model_metadata._cache`` and mock
    the endpoint with respx.
    """
    import time

    from clean_evals import model_metadata

    monkeypatch.setattr(model_metadata, "_cache", (time.monotonic(), {}))


@pytest.fixture
def tmp_artifact_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the local artifact store at a temp dir."""
    monkeypatch.setenv("CLEAN_EVALS_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    return tmp_path / "artifacts"


@pytest.fixture
def sqlite_db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """In-process SQLite for unit tests that need the DB layer."""
    db_path = tmp_path / "clean_evals.sqlite"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("CLEAN_EVALS_DATABASE_URL", url)
    # Reset module-level session factory cache
    from clean_evals.storage import db

    db._session_local = None  # type: ignore[attr-defined]
    return url


@pytest.fixture
def sqlite_engine(sqlite_db_url: str):
    """Engine + bare schema (no Alembic) for fast unit tests."""
    from clean_evals.storage.db import Base, create_engine_from_env

    engine = create_engine_from_env()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
