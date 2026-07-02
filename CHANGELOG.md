# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.1] - 2026-07-02

### Added
- Browser test suite (Playwright, Chromium): six tests drive the served
  application, including dataset creation through the upload wizard. CI
  runs them in a dedicated `e2e` job that gates the required
  `build-wheel` check.

### Changed
- Frontend migrated to React 19 (react, react-dom, and both type
  packages), with all Radix primitives updated to their
  react-19-supporting releases. No source changes were required.
- Dependency bumps: GitHub Actions majors (checkout v7, setup-python v6,
  upload-artifact v7, upload-pages-artifact v5, deploy-pages v5),
  eslint 10, typescript 6, @types/node 26, lucide-react 1.x. Docker base
  images moved to python 3.14-slim and node 26-alpine, and Python 3.14
  was added to the CI test matrix.
- Documentation rewritten as plain technical prose; the project
  description was updated across PyPI metadata, the web UI, and the CLI.

## [0.1.0] - 2026-07-02

### Security
- The SPA catch-all route now resolves paths and refuses to serve files
  outside the static root (path-traversal hardening).
- The Google adapter and connectivity probe authenticate via the
  `x-goog-api-key` header instead of a URL query parameter, keeping the key
  out of error messages, logs, and stored run errors.
- `docker-compose.yml` binds all published ports (web, Redis, MySQL,
  Postgres) to `127.0.0.1`. clean-evals has no auth and is a local tool.

### Fixed
- The daily cost limit now works for CLI runs: today's persisted spend is
  read from storage instead of silently defaulting to $0.
- `upsert_dataset` persists the prompt spec (`request_shape`,
  `system_prompt`, `shared_context`, `user_template`); previously a
  templated dataset saved via `--persist` silently degraded to `raw`.
- An unrecognized model-id prefix now fails only its own cases with
  `status="error"` instead of crashing the whole run.
- The runner closes HTTP clients of adapters it created (`run_sync` no
  longer leaks connections); honored `Retry-After` waits are capped at 120s.
- SQLite connections enable WAL and a 30s busy timeout, avoiding
  "database is locked" errors when the web UI and a run write concurrently.
- Malformed JSON/YAML uploads to the Dataset Builder return 400 instead
  of 500; `clean-evals migrate` reports Alembic failures cleanly.
- `clean-evals serve` honors `CLEAN_EVALS_LOG_LEVEL`.

### Changed
- **License changed from Apache-2.0 to GNU AGPL-3.0 with commercial dual
  licensing.** Use, modification, and redistribution remain free under the
  AGPL's copyleft terms; organizations that cannot accept those obligations
  can obtain a commercial license (`licenses@datathere.com`). The
  in-product attribution is preserved as an additional term under AGPL
  section 7(b).
- Documentation now states plainly that clean-evals is a local tool that
  must not be deployed publicly, and that both cost limits are best-effort
  estimates to be verified against provider billing (README "Disclaimers").
- Cost-ceiling docs reworded from "hard limit" to best-effort semantics.

### Removed
- Unused dependencies: `jinja2`, `tenacity`, `click`, `anyio` (transitively
  provided), `cryptography` (now via `pymysql[rsa]`), and the unused dev
  dependencies `vcrpy`, `pytest-vcr`, `freezegun`.
- Stale `s3` extra references in the Makefile and Dockerfile (the S3
  backend was removed earlier), `default-mysql-client` from the runtime
  image, the unused `@tanstack/react-router` frontend dependency, and the
  never-emitted `run.aborted` event type.

### Added
- Core data models (`Case`, `Dataset`, `ModelResponse`, `ScoreResult`,
  `CaseResult`, `RunConfig`, `RunResult`, `ModelSummary`).
- `Runner` with async core, per-provider concurrency, retry+backoff on 429,
  per-run + daily cost ceilings, deterministic-mode warning.
- Built-in adapters: Anthropic, OpenAI, Google, OpenRouter.
- Built-in scorers: `exact_match`, `json_field_match`, `llm_judge`
  (default judge `claude-haiku-4-5-20251001`).
- Built-in reporters: Markdown, JSONL, JUnit, Console.
- Storage layer: SQLAlchemy models + Alembic migrations (SQLite by default; MySQL and Postgres supported),
  `LocalArtifactStore`.
- Celery + Redis task queue, Celery Beat scheduler, Redis pub/sub for SSE.
- CLI: `serve`, `worker`, `beat`, `migrate`, `run`, `build`, `list-*`,
  `show`, `diff`.
- FastAPI web backend with REST API + SSE.
- React + Vite + Tailwind + Radix frontend with six views: Datasets,
  Run Detail (recommendation cards + leaderboard + heatmap), Cost Projection,
  Live Run, Dataset Builder, Schedules.
- Plugin discovery via Python entry points.
- Three example datasets exercised in CI.
- mkdocs-material documentation site.
- GitHub Actions CI: lint, mypy --strict, pytest 3.11/3.12/3.13, examples,
  PyPI publish on tag, docs deploy on tag.

[Unreleased]: https://github.com/datathere/clean-evals/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/datathere/clean-evals/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/datathere/clean-evals/releases/tag/v0.1.0
