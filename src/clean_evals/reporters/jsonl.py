"""JSONL reporter — one line per ``(case, model)``.

Designed for CI scripts and dashboards. Stable schema documented in
``docs/docs/concepts/reporters.md``. Adding fields ratchets a minor; renaming
or removing fields ratchets a major.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from clean_evals.models import CaseResult, RunResult


class JSONLReporter:
    name: ClassVar[str] = "jsonl"

    def write(self, result: RunResult, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"run_{result.run_id}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for cr in result.cases:
                fh.write(json.dumps(_row(result, cr), ensure_ascii=False) + "\n")
        return path


def _row(result: RunResult, cr: CaseResult) -> dict[str, Any]:
    """One JSONL row schema. Stable contract."""
    score = cr.score.score if cr.score is not None else None
    passed = cr.score.passed if cr.score is not None else None
    return {
        "run_id": result.run_id,
        "dataset": result.dataset,
        "dataset_version": result.dataset_version,
        "case_id": cr.case_id,
        "model": cr.model,
        "status": cr.status,
        "score": score,
        "passed": passed,
        "latency_ms": cr.response.latency_ms if cr.response is not None else None,
        "tokens_in": cr.response.tokens_in if cr.response is not None else None,
        "tokens_out": cr.response.tokens_out if cr.response is not None else None,
        "cost_usd": cr.response.cost_usd if cr.response is not None else None,
        "pricing_version": result.pricing_version,
        "error": cr.error,
        "started_at": cr.started_at.isoformat(),
        "finished_at": cr.finished_at.isoformat(),
    }
