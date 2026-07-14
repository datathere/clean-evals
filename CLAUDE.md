# Using clean-evals from Claude Code

Guide for agents driving clean-evals inside a user's project. clean-evals is a
local eval app that measures AI quality across models against a golden dataset.
It is CLI + local web UI, SQLite by default, and is designed to be operated
by an agent for setup, runs, and telemetry — with the human kept in the loop
for the parts that only a human can do.

Docs live in this repo under `docs/docs/` — read those files directly rather
than fetching from github.io.

## The split: what an agent does, what a human does

**Agent does:**
- Initial install and `.env` setup (asking the user targeted questions, never
  guessing)
- Dataset shape decisions (from a real example the user shows you)
- Wiring telemetry ingestion in the user's application code
- Kicking off eval runs
- Reading the leaderboard and translating it into a recommendation
- **Scoping the human's review queue** — deciding which cases actually need a
  rating and why

**Human does:**
- Blind rating of candidate outputs (1–5, with feedback)
- Locking golden answers
- PII decisions (what to scrub, what's safe to store raw)
- Budget decisions (`--max-cost`, `CLEAN_EVALS_DAILY_COST_LIMIT_USD`)
- Approving the auto-lock lane, if ever

The eval loop only means anything if a human sits behind the ratings. An agent
that rates its own outputs and then evaluates against them is measuring nothing.

## Setup: the interview before you write config

Do not `pip install` and pick defaults. Ask the user first — these choices
lock in early and are painful to change:

1. **Which providers?** They need at least one API key. Anthropic, OpenAI,
   Google, OpenRouter are built in. Local models work through any
   OpenAI-compatible server (Ollama, LM Studio, llama.cpp, vLLM).
2. **Request shape.** How does their app talk to a model? Complete requests
   they ship as-is, or one system prompt with varying inputs, or a
   conversation (chat/transcript)? Ask them to paste one real example before
   you write anything — this drives the dataset schema.
3. **PII.** Ask explicitly. If any input might contain PII, they need a
   `Scrubber` (for YAML datasets) or a `TelemetryScrubber` (for the ingest
   route) before any data is stored. Data is stored **unencrypted** on disk
   otherwise. See `docs/docs/guides/pii.md`.
4. **Budget.** Set `CLEAN_EVALS_DAILY_COST_LIMIT_USD` and, per run, plan on
   `--max-cost`. Both are best-effort — in-flight calls complete after the
   ceiling is hit, so actual spend can overshoot.
5. **Do they need scheduled runs?** If yes, they need Redis plus
   `clean-evals worker` and `clean-evals beat` (or `docker-compose up` for
   the whole stack). If they only run evals on demand, the SQLite +
   `clean-evals serve` default is enough.
6. **Telemetry?** Only if they want production interactions to feed the
   dataset. If yes: set `CLEAN_EVALS_INGEST_TOKEN` and write scrubber first,
   then wire the ingest call in their app.

After these answers, do the standard "run from source" install: create a
venv, `pip install -e ".[dev]"`, build the frontend with `cd web && npm
install && npm run build`, `cp .env.example .env`, fill in the answers,
`clean-evals migrate`, `clean-evals serve`.

`.env.example` ships with `CLEAN_EVALS_LOG_LEVEL=` empty — uvicorn crashes
on that. Set it to `info` (or leave unset by removing the line) before serving.

Always start the server with `clean-evals serve`, never uvicorn directly —
`serve` loads `.env`, seeds the sample datasets, and warns on non-local binds.

## CLI surface

```
clean-evals run              Run an eval over a dataset YAML
clean-evals build            Open the Dataset Builder UI seeded with inputs
clean-evals generate         Generate one candidate output per case and model
clean-evals calibrate        Calibrate the LLM judge against your ratings
clean-evals show             Show a stored run's leaderboard + recommendations
clean-evals diff             Compare two runs by per-model mean score and total cost
clean-evals list-scorers     List registered scorers
clean-evals list-adapters    List registered adapters
clean-evals list-reporters   List registered reporters
clean-evals list-models      List models present in the bundled pricing table
clean-evals migrate          Apply Alembic migrations
clean-evals worker           Start a Celery worker (scheduled runs only)
clean-evals beat             Start the Celery Beat scheduler (scheduled runs only)
clean-evals serve            Start the FastAPI web UI
```

Full reference: `docs/docs/cli.md`.

## The golden path

1. **Bring inputs.** Either upload the user's cases via the Dataset Builder,
   or start from a YAML dataset in `examples/` shape
   (`examples/sentiment/dataset.yml`, `examples/summary_quality/dataset.yml`,
   `examples/json_extraction/dataset.yml`).
2. **Generate candidates.** `clean-evals generate` — a suggested slate is
   two cheap + two medium + two expensive models. Confirm the slate with the
   user before firing, since this spends provider credits.
3. **Blind review — human only.** Do not auto-rate. Hand the user a scoped
   review queue (see next section) and wait.
4. **Lock golden answers — human only.** The locked outputs become the
   reference the judge and future runs score against.
5. **Calibrate the judge.** `clean-evals calibrate` — leave-one-case-out
   agreement is reported as exact-match, within-one, and Cohen's kappa.
   Don't trust the judge below **kappa ≥ 0.6**. If it doesn't clear that,
   the user needs to rate more cases with feedback, not lower the bar.
6. **Run the eval.** `clean-evals run` — pass `--max-cost` explicitly. Runs
   without `--persist` don't count toward the daily budget.
7. **Read the result.** `clean-evals show <run-id>` — three recommendations
   side by side: max accuracy, best price/performance, lowest cost. Translate
   that into a decision for the user; don't just paste the leaderboard.

Concept reading: `docs/docs/concepts/{datasets,scorers,adapters,reporters,recommendations}.md`
and the flow overview at `docs/docs/flow.md`.

## Scoping the review queue — the seam that makes this agent-native

Nobody rates 500 cases. If you tell the user "go review outputs" they will
either bounce or rate randomly. The agent's job is to hand them a short list
with the reason each case matters. Rules of thumb for what to surface:

- **High inter-model variance** — cases where candidates disagree most; a
  rating here actually moves the leaderboard.
- **Cheap-matches-expensive** — cases where the cheap model produced
  substantially the same output as the expensive one; confirming these is
  how a "we don't need the expensive model" recommendation gets earned.
- **Judge-uncertain** — cases where the calibrated judge's confidence or
  spread across candidates is highest; where its opinion is least reliable.
- **New / unrated** — cases with no locked golden answer yet, especially
  ones added since the last calibration.
- **A small random sample** — mix in ~10% random cases as a bias check
  against the scoping heuristics themselves.

Present each with the reason: "rate this — top-3 models disagreed by 2+
points" / "rate this — cheap model matched expensive, confirming this saves
$X/mo." Never present without a reason; the reason is what makes the
review efficient.

## Telemetry: wiring production data into the loop

For app builders using clean-evals to keep an eye on a shipped agent, see
`docs/docs/guides/telemetry.md`. Highlights the agent should know:

- **Two envelope types.** `structured` (request + response + user's field
  edits/accept, deterministic derivation, free) vs `transcript` (whole
  conversation, split into per-turn exchanges, needs one classifier call per
  transcript).
- **Two ingress paths.** `POST /api/v1/telemetry/interactions` (token-gated
  via `CLEAN_EVALS_INGEST_TOKEN` — dark until that's set) or JSONL upload in
  the UI. Working samples: `examples/telemetry/structured.jsonl` and
  `examples/telemetry/transcripts.jsonl`.
- **Scrubber first, always.** If the user has any PII, wire a
  `TelemetryScrubber` before the first envelope is sent. Raw envelopes are
  stored as-is otherwise.
- **Human confirms.** Derived exchanges land in a review inbox; a human
  promotes them into golden dataset cases.
- **Auto-lock lane.** Do **not** enable on first setup. It only makes sense
  once the judge is calibrated on a meaningful dataset and the user has
  seen a few weeks of the human review inbox to build intuition for their
  own overturn rate.
- **The ingest token protects one route.** It authenticates the ingest
  endpoint and nothing else. Forwarding only that path through a proxy is
  fine; exposing the whole instance is not.

## Danger zones

- **Local tool.** No authentication anywhere. Bind to localhost. The Docker
  compose file binds every port to `127.0.0.1` for this reason. Never
  expose to a network the user doesn't fully control.
- **Data is plain text on disk.** Prompts, outputs, datasets, reports live
  unencrypted under `./clean-evals-data/`. Treat that directory as
  sensitive. No built-in retention or cleanup.
- **Cost limits are best-effort.** `--max-cost` is checked as results
  arrive; in-flight calls complete. `CLEAN_EVALS_DAILY_COST_LIMIT_USD`
  counts only *persisted* runs (web, scheduled, and CLI with `--persist`).
  Always tell the user to verify actual spend in the provider's billing
  console.
- **Cost figures are estimates.** Bundled pricing snapshot + optional local
  overrides. Recommendations are informed guesses, not invoices.
- **Data is sent to model providers.** Every case input goes to the
  third-party APIs of the models selected, under those providers' terms.
- **PII is not scrubbed automatically.** UI uploads and unscrubbed
  telemetry land as-is.
- **SQLite default is single-user.** For a shared team instance, use the
  MySQL or Postgres backends — and put the whole thing on infrastructure
  the user controls.
- **Auto-lock hides bad ratings from human review.** Do not enable it
  proactively. When it is enabled, it disables itself if the human overturn
  rate climbs — respect that signal.

## Local doc index

Read these directly instead of fetching from the web:

- `README.md` — product overview
- `docs/docs/getting-started.md`
- `docs/docs/flow.md` — the golden path
- `docs/docs/api.md` — HTTP API reference
- `docs/docs/cli.md` — CLI reference
- `docs/docs/concepts/{datasets,scorers,adapters,reporters,recommendations}.md`
- `docs/docs/guides/{telemetry,pii,cost-ceilings,dataset-builder,deployment}.md`
- `docs/docs/guides/{writing-a-scorer,writing-an-adapter,writing-a-reporter}.md`
- `examples/` — dataset YAML shapes
- `examples/telemetry/` — envelope shapes
- `.env.example` — every env var, commented
