"""FastAPI application entry point.

Routes:

- ``/api/v1/datasets`` — list/create/version datasets.
- ``/api/v1/datasets/{id}/cases`` — case CRUD for the Dataset Builder.
- ``/api/v1/runs`` — list runs, fetch run detail, trigger runs.
- ``/api/v1/runs/{id}/recommendations`` — three side-by-side cards.
- ``/api/v1/runs/{id}/cost-projection`` — calculator endpoint.
- ``/api/v1/schedules`` — schedule CRUD.
- ``/api/v1/events`` — SSE stream of live run progress.
- ``/api/v1/builder/upload`` — multi-format input upload (CSV/JSON/JSONL/YAML).
- ``/api/v1/runs/{id}/artifacts/{name}`` — fetch a stored artifact.

Static frontend mounted at ``/`` (with a catch-all so the React router
owns deep links).
"""

from __future__ import annotations

import logging
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from clean_evals._internal.version import __version__
from clean_evals.web.api import builder, datasets, events, goldenpath, models, runs, schedules

_log = logging.getLogger(__name__)


def _static_dir() -> Path:
    return Path(str(files("clean_evals.web") / "static"))


app = FastAPI(
    title="clean-evals",
    version=__version__,
    description="Measure AI quality across models. Decisions, not data.",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router, prefix="/api/v1")
app.include_router(goldenpath.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(schedules.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(builder.router, prefix="/api/v1")
app.include_router(models.router, prefix="/api/v1")


@app.get("/api/v1/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness probe for orchestrators."""
    return {"status": "ok", "version": __version__}


# ---------------------------------------------------------------------------
# SPA: serve the bundled React app under "/".
# ---------------------------------------------------------------------------

_static_root = _static_dir()
_static_root_resolved = _static_root.resolve()
if _static_root.exists() and any(_static_root.iterdir()):
    app.mount(
        "/assets", StaticFiles(directory=_static_root / "assets", check_dir=False), name="assets"
    )

    index_path = _static_root / "index.html"

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(index_path)

    @app.get("/{path:path}", include_in_schema=False)
    def catch_all(path: str) -> Response:
        if path.startswith("api/"):
            return Response(status_code=404)
        # Resolve + containment check: the raw path can carry traversal
        # sequences, and nothing outside the static root may be served.
        candidate = (_static_root / path).resolve()
        if candidate.is_relative_to(_static_root_resolved) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_path)

else:

    @app.get("/", include_in_schema=False)
    def index_dev() -> dict[str, str]:
        return {
            "message": (
                "Frontend not built. Run 'cd web && npm run build' or use "
                "'npm run dev' against this API."
            ),
            "api_docs": "/api/docs",
        }
