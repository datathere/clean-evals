"""Celery + Redis queue.

Layout:

- ``app`` — Celery application object. Imported by ``clean-evals worker``
  and ``clean-evals beat`` via ``-A clean_evals.queue.app``.
- ``tasks`` — task definitions (``run_eval``).
- ``events`` — Redis pub/sub plumbing for SSE.
- ``schedule`` — DB-backed Celery Beat schedule loader.
"""

from __future__ import annotations

from clean_evals.queue.app import app

__all__ = ["app"]
