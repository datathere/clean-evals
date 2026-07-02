"""Per-case diff generator.

When a case fails, ``case_<id>.diff.md`` lands next to the run report with
the prompt sent, the expected vs actual side-by-side, the raw response, and
the scorer breakdown. This is the drill-down link the Markdown reporter
points to.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

from clean_evals.models import Case, CaseResult


def write_case_diff(
    case: Case,
    case_result: CaseResult,
    output_dir: Path,
) -> Path:
    """Write a Markdown diff file for one case. Returns the path written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = case.id.replace("/", "_").replace(":", "_")
    path = output_dir / f"case_{safe_id}__{case_result.model}.diff.md"

    expected_text = json.dumps(case.expected or {}, indent=2, ensure_ascii=False, sort_keys=True)
    actual_text = ""
    if case_result.response is not None:
        if case_result.response.parsed is not None:
            actual_text = json.dumps(
                case_result.response.parsed, indent=2, ensure_ascii=False, sort_keys=True
            )
        else:
            actual_text = case_result.response.content

    diff_lines = difflib.unified_diff(
        expected_text.splitlines(),
        actual_text.splitlines(),
        fromfile="expected",
        tofile="actual",
        lineterm="",
    )

    score_block = ""
    if case_result.score is not None:
        score_block = (
            f"**Score:** {case_result.score.score:.3f} " f"(passed: {case_result.score.passed})\n\n"
        )
        if case_result.score.breakdown:
            score_block += "**Breakdown:**\n"
            for k, v in case_result.score.breakdown.items():
                score_block += f"- `{k}`: {v:.3f}\n"
            score_block += "\n"
        if case_result.score.notes:
            score_block += f"**Notes:** {case_result.score.notes}\n\n"

    error_block = ""
    if case_result.error:
        error_block = f"**Error:** `{case_result.error}`\n\n"

    raw_block = ""
    if case_result.response is not None:
        raw_block = (
            "<details><summary>Raw provider response</summary>\n\n"
            "```json\n"
            + json.dumps(case_result.response.raw, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n```\n\n</details>\n"
        )

    body = (
        f"# Case `{case.id}` · model `{case_result.model}`\n\n"
        f"**Status:** `{case_result.status}`\n\n"
        f"{score_block}{error_block}"
        "## Input\n\n```json\n"
        + json.dumps(case.input, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n```\n\n"
        "## Expected\n\n```json\n" + expected_text + "\n```\n\n"
        "## Actual\n\n```\n" + actual_text + "\n```\n\n"
        "## Diff\n\n```diff\n" + "\n".join(diff_lines) + "\n```\n\n" + raw_block
    )
    path.write_text(body, encoding="utf-8")
    return path
