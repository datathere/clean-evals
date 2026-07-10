# Public API

This page lists the public API. Everything not listed here is
implementation detail.

Anything under `clean_evals._internal` may change without notice. The public
surface follows SemVer; breaking changes ratchet majors. Pre-1.0, minor
versions may break the public API with a `CHANGELOG.md` entry.

## Stability tags

- ![stable](https://img.shields.io/badge/stable-success) — won't change without a major bump.
- ![beta](https://img.shields.io/badge/beta-orange) — may change at minor bumps with deprecation notice.

## Data models

::: clean_evals.Case
::: clean_evals.Dataset
::: clean_evals.ModelResponse
::: clean_evals.ScoreResult
::: clean_evals.CaseResult
::: clean_evals.RunConfig
::: clean_evals.ModelSummary
::: clean_evals.RunResult

## Runner

::: clean_evals.Runner

## Telemetry envelopes

::: clean_evals.StructuredInteraction
::: clean_evals.TranscriptInteraction

## Plugin protocols

::: clean_evals.Scorer
::: clean_evals.ModelAdapter
::: clean_evals.Reporter
::: clean_evals.Scrubber
::: clean_evals.TelemetryScrubber
