"""Integration-test fixtures.

- ``fake_openai_server`` starts a stdlib HTTP server that speaks the
  OpenAI-compatible ``/chat/completions`` and ``/models`` API. Tests
  point the real ``local`` adapter at it via
  ``CLEAN_EVALS_LOCAL_BASE_URL``, exercising the whole stack (adapter,
  runner, queue, web) with no API cost and no network.
- ``migrated_sqlite`` builds a temp SQLite database through the real
  Alembic migration chain (not ``create_all``), so migrations are under
  test.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fake OpenAI-compatible provider
# ---------------------------------------------------------------------------


def _classify(prompt: str) -> str:
    """A trivial deterministic 'model': echo a plausible label so scored
    runs produce a spread of pass/fail without any real inference."""
    low = prompt.lower()
    if "positive" in low or "love" in low or "great" in low:
        return "positive"
    if "negative" in low or "hate" in low or "terrible" in low:
        return "negative"
    return "neutral"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # silence
        pass

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._json(
                200,
                {"object": "list", "data": [{"id": "fake-1", "object": "model"}]},
            )
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages", [])
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        wants_json = (body.get("response_format") or {}).get("type") == "json_object"
        label = _classify(user)
        content = json.dumps({"label": label}) if wants_json else label
        self._json(
            200,
            {
                "id": "chatcmpl-fake",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    def _json(self, status: int, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_openai_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Run the fake provider on a random port; yield its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    monkeypatch.setenv("CLEAN_EVALS_LOCAL_BASE_URL", base)
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Migrated database (real Alembic chain)
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A SQLite database migrated from empty through the Alembic chain."""
    db_path = tmp_path / "migrated.sqlite"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("CLEAN_EVALS_DATABASE_URL", url)

    from clean_evals.storage import db as db_module
    from clean_evals.storage.migrations.runner import upgrade

    db_module._session_local = None  # type: ignore[attr-defined]
    upgrade("head")
    try:
        yield url
    finally:
        db_module._session_local = None  # type: ignore[attr-defined]
