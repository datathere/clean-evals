"""ArtifactStore — persists rendered reports and per-case diffs.

:class:`LocalArtifactStore` writes under ``./clean-evals-data/artifacts/``
(override via ``CLEAN_EVALS_ARTIFACT_DIR``). ``ArtifactStore`` is a
protocol, so a deployment that wants object storage can provide its own
implementation and wire it where :func:`build_artifact_store` is called.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import IO, Protocol, runtime_checkable
from urllib.parse import urlparse


@runtime_checkable
class ArtifactStore(Protocol):
    """Stores rendered reports keyed by run id.

    Implementations must be thread-safe — the FastAPI app and Celery
    workers share an instance.
    """

    def write_dir(self, run_id: str, source_dir: Path) -> str: ...

    def open_read(self, uri: str, name: str) -> IO[bytes]: ...

    def list(self, uri: str) -> list[str]: ...

    def url_for(self, uri: str, name: str) -> str: ...


class LocalArtifactStore:
    """File-system backed store. Default."""

    def __init__(self, root: Path | str | None = None) -> None:
        env_root = os.environ.get("CLEAN_EVALS_ARTIFACT_DIR")
        self._root = Path(root or env_root or "./clean-evals-data/artifacts").resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def write_dir(self, run_id: str, source_dir: Path) -> str:
        target = self._root / run_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_dir, target)
        return target.as_uri()

    def open_read(self, uri: str, name: str) -> IO[bytes]:
        path = self._resolve(uri) / name
        return path.open("rb")

    def list(self, uri: str) -> list[str]:
        path = self._resolve(uri)
        if not path.exists():
            return []
        return sorted(p.name for p in path.iterdir() if p.is_file())

    def url_for(self, uri: str, name: str) -> str:
        return (self._resolve(uri) / name).as_uri()

    def _resolve(self, uri: str) -> Path:
        if uri.startswith("file://"):
            from urllib.request import url2pathname

            return Path(url2pathname(urlparse(uri).path))
        return Path(uri)


def build_artifact_store() -> ArtifactStore:
    """The artifact store for this install — local filesystem."""
    return LocalArtifactStore()
