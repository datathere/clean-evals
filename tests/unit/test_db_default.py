"""Zero-config database default — SQLite, no env var required."""

from __future__ import annotations

from pathlib import Path

import pytest

from clean_evals.storage.db import Base, create_engine_from_env


def test_defaults_to_sqlite_when_env_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest strips CLEAN_EVALS_DATABASE_URL; run from a temp cwd so the
    # default data dir lands there.
    monkeypatch.chdir(tmp_path)
    engine = create_engine_from_env()
    try:
        assert engine.url.get_backend_name() == "sqlite"
        Base.metadata.create_all(engine)
        assert (tmp_path / "clean-evals-data" / "clean_evals.sqlite").exists()
    finally:
        engine.dispose()


def test_env_var_still_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CLEAN_EVALS_DATABASE_URL", f"sqlite:///{(tmp_path / 'x.sqlite').as_posix()}"
    )
    engine = create_engine_from_env()
    try:
        assert "x.sqlite" in str(engine.url)
    finally:
        engine.dispose()
