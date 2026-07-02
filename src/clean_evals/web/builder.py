"""``clean-evals build`` helper — seed a dataset for the Builder UI."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import yaml

from clean_evals.errors import ConfigError
from clean_evals.storage.db import CaseRow, DatasetRow, session_factory


def seed_in_progress_dataset(
    inputs_path: Path,
    *,
    name: str,
    version: str,
    scorer: str,
) -> int:
    """Read ``inputs_path`` and insert an in-progress dataset row + cases."""
    rows = _read_rows(inputs_path)
    if not rows:
        raise ConfigError(f"{inputs_path}: no input rows found")

    factory = session_factory()
    with factory() as session:
        ds = DatasetRow(name=name, version=version, scorer=scorer, scorer_config={})
        session.add(ds)
        session.flush()
        for i, row in enumerate(rows):
            external = str(row.get("id") or f"case_{i + 1:04d}")
            session.add(
                CaseRow(
                    dataset_id=ds.id,
                    case_id_external=external,
                    input_jsonb=row,
                    expected_jsonb=None,
                    tags_jsonb=[],
                    locked=False,
                    metadata_jsonb={},
                )
            )
        session.commit()
        return ds.id


def _read_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [dict(r) for r in csv.DictReader(io.StringIO(text))]
    if suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if suffix == ".json":
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ConfigError(f"{path}: JSON must be an array of objects")
        return parsed
    if suffix in {".yml", ".yaml"}:
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, list):
            raise ConfigError(f"{path}: YAML must be a top-level list")
        return parsed
    raise ConfigError(f"{path}: unsupported extension; use csv/json/jsonl/yaml")
