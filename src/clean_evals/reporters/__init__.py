"""Built-in reporters."""

from __future__ import annotations

from clean_evals.reporters.console import ConsoleReporter
from clean_evals.reporters.diff import write_case_diff
from clean_evals.reporters.jsonl import JSONLReporter
from clean_evals.reporters.junit import JUnitReporter
from clean_evals.reporters.markdown import MarkdownReporter

__all__ = [
    "ConsoleReporter",
    "JSONLReporter",
    "JUnitReporter",
    "MarkdownReporter",
    "write_case_diff",
]
