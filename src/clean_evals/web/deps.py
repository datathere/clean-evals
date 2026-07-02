"""FastAPI dependencies.

Most endpoints want a SQLAlchemy ``Session``; ``get_session`` provides one
within the request scope. Tests can override via ``app.dependency_overrides``.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from clean_evals.storage.db import session_factory


def get_session() -> Iterator[Session]:
    """Yield a transaction-managed ``Session``."""
    factory = session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
