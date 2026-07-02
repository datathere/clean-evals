"""Programmatic Alembic entry point.

Wraps Alembic's :class:`~alembic.config.Config` so ``clean-evals migrate``
doesn't shell out to ``alembic`` and the wheel ships everything it needs.
"""

from __future__ import annotations

from importlib.resources import as_file, files

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from clean_evals.storage.db import create_engine_from_env


def alembic_config() -> Config:
    """Build an Alembic :class:`Config` pointing at the bundled migrations."""
    pkg = files("clean_evals.storage.migrations")
    with as_file(pkg / "alembic.ini") as ini_path, as_file(pkg) as script_path:
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(script_path))
        # The URL in alembic.ini is a placeholder. The env.py uses
        # create_engine_from_env() to obtain the real engine, so all we need
        # is to set *something* parseable here for offline-mode users.
        cfg.set_main_option(
            "sqlalchemy.url",
            "sqlite:///./clean_evals_alembic_default.sqlite",
        )
        return cfg


def upgrade(revision: str = "head") -> None:
    """``alembic upgrade <revision>``."""
    # Ensure the engine works before invoking Alembic — creates the default
    # SQLite database when CLEAN_EVALS_DATABASE_URL is unset.
    create_engine_from_env()
    command.upgrade(alembic_config(), revision)


def downgrade(revision: str) -> None:
    """``alembic downgrade <revision>``."""
    create_engine_from_env()
    command.downgrade(alembic_config(), revision)


def current() -> str | None:
    """Return the current revision id, or ``None`` if the DB is empty."""
    engine = create_engine_from_env()
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        return context.get_current_revision()
