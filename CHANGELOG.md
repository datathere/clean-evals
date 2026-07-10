# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Telemetry ingestion** (docs: `guides/telemetry.md`). Production
  interactions enter through a token-gated batch endpoint
  (`POST /api/v1/telemetry/interactions`; the route answers 404 until
  `CLEAN_EVALS_INGEST_TOKEN` is set) or a JSONL upload, are stored
  losslessly, and derive into reviewable exchanges. Two envelope kinds:
  `structured` (accept-or-edit: edit ratio → implicit 1–5 rating, field
  diffs → feedback, committed output → proposed golden answer) and
  `transcript` (whole conversations exploded into per-turn exchanges; the
  next user message is classified as the review of the previous response
  by one small-model call per transcript, metered by
  `CLEAN_EVALS_TELEMETRY_DAILY_COST_LIMIT_USD`). Missing accept signals
  derive as unrated, never guessed.
- **Telemetry inbox and monitoring pages.** Reviewing a derived exchange
  promotes it — case, candidate outputs (including discarded
  regenerations), implicit rating (`ratings.source="implicit"`) — or
  discards it. Auto-created datasets preserve the production request
  faithfully: transcripts get a chat-shaped dataset with the system
  prompt carried per case; structured interactions get a templated one
  with the system prompt taken from the first promoted interaction. Monitoring charts acceptance rate, mean implicit rating,
  corrections per turn, and turns-to-accept per source and model, with
  optional judge-scored sampling (off by default;
  `CLEAN_EVALS_TELEMETRY_JUDGE_SAMPLE_RATE`).
- **Auto-lock lane (opt-in, self-measuring).** With
  `CLEAN_EVALS_TELEMETRY_AUTOLOCK=1`, an exchange with an explicit accept,
  implicit rating ≥ 4, and a calibrated judge (kappa ≥ 0.6) that passes
  the response is promoted and locked without review; a spot-check sample
  routes to a human anyway, and the lane disables itself when the
  overturn rate crosses a threshold.
- **`request_shape: "chat"`.** Cases promoted from transcripts carry their
  conversation prefix and eval runs replay it verbatim as message history.
  The `ModelAdapter` protocol gains an optional keyword-only `history`
  parameter, implemented by all five built-in adapters; the runner passes
  it only when a case has history, so pre-chat adapters keep working for
  single-shot datasets (see `API.md`).
- **`TelemetryScrubber` protocol** (entry-point group
  `clean_evals.telemetry_scrubbers`, selected via
  `CLEAN_EVALS_TELEMETRY_SCRUBBER`) runs on every envelope before it is
  persisted; without one, envelopes are stored raw and the UI says so.
- Sample envelopes of both kinds in `examples/telemetry/`.

### Fixed
- A case whose request cannot be assembled (missing template field,
  malformed chat context) now fails alone with `status="error"` instead of
  crashing the run.
- Findings from the pre-release review of the telemetry feature, all with
  regression tests:
    - The classifier's daily ceiling is keyed on when the classifier ran
      (`classified_at`, migration `0005`), not on ingest time — a backlog
      ingested before midnight can no longer re-spend the full ceiling.
    - Concurrent retries of the same ingest batch no longer 500: each
      insert flushes inside a savepoint, so a duplicate that slips past
      the existence check rolls back as a per-item duplicate.
    - Chat assembly merges consecutive same-role turns and folds a
      trailing user turn into the final message, satisfying providers that
      reject non-alternating roles (Anthropic, Google).
    - A follow-up user message is attributed only to the response it
      immediately follows; with consecutive assistant turns, nothing is
      attributed to the wrong exchange, and the terminal outcome speaks
      only for the transcript's last assistant turn.
    - The auto-lock judge scores exchanges against the calibrated standard
      with no expected answer — previously it compared the response to the
      proposed golden, which for untouched accepts is the response itself
      (a circular, always-passing signal). It also reads kappa from the
      calibration summary where it is actually stored.
    - Promotion refuses a structured exchange into a chat-shaped dataset
      (the reverse guard already existed); switching a dataset to
      `request_shape="chat"` is refused with 400 when its cases lack the
      `message` field, instead of burning a 100%-error run.
    - The request preview includes the replayed conversation turns for
      chat-shaped cases; the ingest token gate returns 401 (not 500) for
      non-ASCII bearer values; non-UTF-8 telemetry uploads return 400.
    - Promotion preserves the production system prompt (per case for
      transcripts, dataset-level for structured) and creates templated
      datasets for structured telemetry so replays match what production
      sent.

## [0.2.0] - 2026-07-02

### Added
- `local` adapter for OpenAI-compatible endpoints (Ollama, LM Studio,
  llama.cpp server, vLLM, and hosted gateways). Model ids use the
  `local/` prefix (`local/llama3.2`); configure with
  `CLEAN_EVALS_LOCAL_BASE_URL` (defaults to Ollama's
  `http://localhost:11434/v1`) and optional `CLEAN_EVALS_LOCAL_API_KEY`.
  The Models page lists installed local models when the server is
  reachable, local runs cost $0.00 unless a pricing override is set, and
  the dated-snapshot rule does not apply to `local/` ids.
- Clicking a dataset row opens the case editor; the run detail page has
  a Re-run button that repeats the run with the same dataset version and
  config; unknown URLs render a not-found page.

### Fixed
- Provider inference covers the whole OpenAI o-series (`o3`, `o3-mini`,
  `o4-mini`); previously only `o1*` routed.
- A provider with no registered adapter fails its own cases with
  `status="error"` instead of crashing the run.
- Per-case diff filenames sanitize `/` and `:` in model ids (local/
  prefixes, Ollama tags, OpenRouter slugs).

### Changed
- The Dataset Builder nav item is removed; the Datasets page owns
  dataset creation and editing.

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

[Unreleased]: https://github.com/datathere/clean-evals/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/datathere/clean-evals/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/datathere/clean-evals/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/datathere/clean-evals/releases/tag/v0.1.0
