"""FastAPI web app + REST API.

Mounted under ``clean-evals serve``. Static React assets live in
``clean_evals/web/static/`` (populated by the build hook from ``web/dist/``).
The REST API is mounted at ``/api/v1``; SSE endpoint at ``/api/v1/events``;
SPA routes are served by an HTML5 history-mode catch-all so the React app
owns ``/datasets``, ``/runs/<id>``, ``/builder``, etc.
"""

from __future__ import annotations

from clean_evals.web.app import app

__all__ = ["app"]
