# CLI reference

```text
clean-evals --help
```

## Subcommands

| Command                  | Purpose                                         |
| ------------------------ | ----------------------------------------------- |
| `serve [--host --port]`  | Start the FastAPI web UI                        |
| `worker [--concurrency]` | Celery worker process                           |
| `beat`                   | Celery Beat scheduler with the DB-backed schedule|
| `migrate [--revision]`   | Apply Alembic migrations                        |
| `run <dataset> ...`      | Headless eval run                               |
| `generate <dataset_id>`  | Generate candidate outputs for the golden path  |
| `calibrate <dataset_id>` | Calibrate the LLM judge against your ratings    |
| `build <inputs>`         | Open the Dataset Builder UI seeded from inputs  |
| `show <run_id>`          | Print a stored run's leaderboard                |
| `diff <run_a> <run_b>`   | Compare two runs by score and cost              |
| `list-scorers`           | Registered scorers                              |
| `list-adapters`          | Registered adapters                             |
| `list-reporters`         | Registered reporters                            |
| `list-models`            | Models with bundled pricing entries             |

## `clean-evals generate` and `clean-evals calibrate`

The golden path's stages 2 and 4 from the terminal:

```text
clean-evals generate 5 --models gpt-5-mini,claude-sonnet-4-6 [--max-cost 5.0] [--temperature 0.0]
clean-evals calibrate 5 [--judge claude-haiku-4-5-20251001]
```

`generate` produces one candidate output per case and model; outputs are
not scored, and the command prints the Dataset Builder URL where you rate
them. `calibrate` requires rated outputs, prints the judge agreement
(exact, within ±1, kappa), stores a new judge configuration version, and
warns when kappa lands below 0.6.

## `clean-evals run` options

```text
--models claude-3-5-sonnet-20241022,gpt-4o-2024-11-20
--timeout 120
--seed 42
--temperature 0.0
--max-cost 5.00
--output ./results
--reporters markdown,jsonl,junit,console
--baseline <run_id>
--fail-on-regression
--fail-on-score 0.85
--persist
```

## Exit codes

| Code | Meaning                                     |
| ---: | ------------------------------------------- |
|  `0` | Success                                     |
|  `1` | Regression detected against `--baseline`    |
|  `2` | Score below `--fail-on-score`               |
|  `3` | Config invalid                              |
|  `4` | Cost ceiling reached                        |
| 64–78 | Standard `sysexits` for unforeseen failures |

## Provider auth

clean-evals reads keys from environment variables. There is no
`clean-evals login`.

| Provider     | Env var                |
| ------------ | ---------------------- |
| Anthropic    | `ANTHROPIC_API_KEY`    |
| OpenAI       | `OPENAI_API_KEY`       |
| Google       | `GOOGLE_API_KEY`       |
| OpenRouter   | `OPENROUTER_API_KEY`   |

For multiple profiles, drop a `~/.config/clean-evals/config.toml` and
swap with a profile flag (planned post-v0.4).
