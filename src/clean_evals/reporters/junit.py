"""JUnit XML reporter for surfacing eval results in CI test UIs.

One ``<testcase>`` per ``(case, model)``. ``passed=False`` is a test
failure with the case's diff embedded as the failure message. Errors
(timeout, schema_invalid, aborted_cost) are encoded as ``<error>``.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar
from xml.sax.saxutils import escape

from clean_evals.models import CaseResult, RunResult


class JUnitReporter:
    name: ClassVar[str] = "junit"

    def write(self, result: RunResult, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"run_{result.run_id}.junit.xml"
        path.write_text(_render(result), encoding="utf-8")
        return path


def _render(result: RunResult) -> str:
    total_failures = sum(
        1 for c in result.cases if c.status == "ok" and c.score is not None and not c.score.passed
    )
    total_errors = sum(1 for c in result.cases if c.status != "ok")
    duration = (result.finished_at - result.started_at).total_seconds()

    lines: list[str] = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<testsuites name="clean-evals" tests="{len(result.cases)}" failures="{total_failures}" '
        f'errors="{total_errors}" time="{duration:.3f}">',
    ]

    by_model: dict[str, list[CaseResult]] = {}
    for c in result.cases:
        by_model.setdefault(c.model, []).append(c)

    for model, cases in by_model.items():
        suite_failures = sum(
            1 for c in cases if c.status == "ok" and c.score is not None and not c.score.passed
        )
        suite_errors = sum(1 for c in cases if c.status != "ok")
        suite_time = sum((c.finished_at - c.started_at).total_seconds() for c in cases)
        lines.append(
            f'  <testsuite name="{escape(model)}" tests="{len(cases)}" '
            f'failures="{suite_failures}" errors="{suite_errors}" time="{suite_time:.3f}">'
        )
        for c in cases:
            elapsed = (c.finished_at - c.started_at).total_seconds()
            classname = f"{result.dataset}.{model}"
            name = c.case_id
            opening = (
                f'    <testcase classname="{escape(classname)}" '
                f'name="{escape(name)}" time="{elapsed:.3f}">'
            )
            if c.status != "ok":
                lines.append(opening)
                lines.append(
                    f'      <error type="{escape(c.status)}">' f"{escape(c.error or '')}</error>"
                )
                lines.append("    </testcase>")
            elif c.score is not None and not c.score.passed:
                lines.append(opening)
                msg = f"score={c.score.score:.3f}, threshold not met"
                lines.append(
                    f'      <failure message="{escape(msg)}" type="ScoreBelowThreshold">'
                    f"{escape(c.score.notes or '')}</failure>"
                )
                lines.append("    </testcase>")
            else:
                lines.append(opening[:-1] + " />")
        lines.append("  </testsuite>")

    lines.append("</testsuites>")
    return "\n".join(lines) + "\n"
