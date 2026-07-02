# Running clean-evals

clean-evals is a **local tool** for single-user / single-team use. There is
no authentication at any layer: anyone who can reach the port can read and
edit datasets and trigger runs that spend real provider credits.

Bind to localhost — that is the default everywhere, including the Docker
setup. Binding to a non-loopback address is explicitly your choice and your
responsibility; if you must share an instance, keep it on a private network
you control and put a reverse proxy with authentication in front of it.
clean-evals is not designed to be exposed to the public internet, with or
without a proxy.

## Single-host install

```bash
pip install clean-evals
clean-evals migrate

# Run these as separate services (systemd, supervisor, nohup):
clean-evals worker --concurrency 4
clean-evals beat
clean-evals serve                    # binds 127.0.0.1:8080
```

`worker` and `beat` are only needed for scheduled runs; interactive use works
with `serve` alone.

## Docker

```bash
git clone https://github.com/datathere/clean-evals
cd clean-evals
cp .env.example .env
docker-compose up
```

`docker-compose.yml` brings up MySQL (or Postgres if `DB_FLAVOR=postgres`),
Redis, the worker, beat, and the web server in one command. Every published
port binds to `127.0.0.1`, so nothing is reachable from other machines. The
bundled database and Redis credentials are development defaults — one more
reason the stack must stay local.

## Artifacts

Rendered reports are written to `./clean-evals-data/artifacts/`. Set
`CLEAN_EVALS_ARTIFACT_DIR` to change the location. `ArtifactStore` is a
protocol, so an installation can provide its own storage implementation.

Artifacts and database rows contain your prompts and model outputs in plain
text. Treat the data directory as sensitive.

## Postgres backend (optional)

```bash
pip install "clean-evals[postgres]"
export CLEAN_EVALS_DATABASE_URL=postgresql+psycopg2://user:pass@host/db
clean-evals migrate
```

## Cost safety nets

Both limits are **best-effort**. They reduce the blast radius of a mistake;
they do not guarantee a spend ceiling. Always verify actual spend in your
provider's billing console.

- **Per-run limit:** `--max-cost` (default $5). Spend is checked as results
  arrive; cases that have not started when the ceiling trips are aborted,
  but calls already in flight complete, so the run can overshoot the limit
  (bounded by how many calls run concurrently).
- **Daily limit:** the `CLEAN_EVALS_DAILY_COST_LIMIT_USD` env var. The runner
  refuses to start a new run once today's cumulative spend meets the limit.
  Only *persisted* runs count toward the total — web and scheduled runs, and
  CLI runs with `--persist`. CLI runs without `--persist` leave no cost
  trail and are invisible to this check.

## Run retention

By default, run rows are kept forever. Set
`CLEAN_EVALS_RUN_RETENTION_DAYS=365` to enable a janitor (planned).
