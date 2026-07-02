# Getting started

This page covers installation, a first eval run against an example
dataset, and opening the results in the Decision UI.

## 1. Install

=== "Manual (recommended for Python devs)"

    ```bash
    # System packages
    brew install redis mysql                    # macOS
    apt install redis-server mysql-server       # Linux
    winget install redis mysql                  # Windows

    # clean-evals
    pip install clean-evals
    clean-evals migrate
    ```

=== "Docker"

    ```bash
    git clone https://github.com/datathere/clean-evals
    cd clean-evals
    cp .env.example .env       # edit with your API keys
    docker-compose up
    # Web UI: http://localhost:8080
    ```

## 2. Configure provider keys

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
# (optional)
export GOOGLE_API_KEY=...
export OPENROUTER_API_KEY=...
```

clean-evals reads provider keys directly from environment variables. There
is no `clean-evals login`. For multiple profiles, use a per-profile env
file and `set -a; source profile.env; set +a`.

## 3. Run an example dataset

```bash
clean-evals run examples/sentiment/dataset.yml \
  --models claude-3-5-sonnet-20241022,gpt-4o-mini-2024-07-18 \
  --max-cost 0.50 \
  --output ./results
```

The run writes its artifacts to `./results/`:

- `run_<id>.md` — Markdown report (paste into a PR).
- `run_<id>.jsonl` — one row per `(case, model)` for scripts.
- A console-rendered table.

## 4. Open the Decision UI

```bash
clean-evals worker &       # or in another terminal
clean-evals beat &         # for scheduled runs
clean-evals serve          # http://localhost:8080
```

You'll see your run on the **Runs** page. Click it for the Decision view:

- Three side-by-side recommendation cards with the numbers behind each pick.
- A sortable leaderboard.
- A per-case heatmap. Click any cell to see the expected vs actual diff.
- A cost-projection calculator.

## 5. Build your own dataset

Upload a CSV / JSON / JSONL / YAML file of inputs to the **Dataset Builder**:

```bash
clean-evals build my_inputs.csv --name my_eval --version v1
```

The UI runs candidate models on your inputs, shows the outputs side
by side, and lets you pick or edit the best one. Locked cases become
`Case` rows with `expected` set.

## What's next

- [Concepts: how the recommendations are computed](concepts/recommendations.md)
- [Writing a custom scorer](guides/writing-a-scorer.md)
- [Running clean-evals against production data (PII)](guides/pii.md)
- [Deployment](guides/deployment.md)
