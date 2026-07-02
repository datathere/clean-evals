# Contributing to clean-evals

Thank you for considering a contribution. clean-evals aims to be the kind of
project a senior engineer reads and trusts in fifteen minutes — please help
us keep that bar high.

By submitting a contribution, you agree that it is provided under the
project's [AGPL-3.0 license](LICENSE) and you grant datathere the right to
include it in commercially licensed distributions of the software.

## Ground rules

1. **Boring, typed Python.** Strict `mypy --strict`. No `Any`, no
   `# type: ignore` without justification, no metaclass tricks. Pydantic v2
   for every public data model.
2. **Pure-async core.** Adapters and the runner are `async`-native. Sync
   wrappers exist only at the user-facing boundary.
3. **Zero-magic config.** Pydantic with `extra="forbid"`. No env-var
   interpolation and no template engine — the only substitution is the
   documented `{field}` placeholders in a dataset's prompt template.
4. **Tests are first-class.** Coverage is enforced in CI (see `fail_under`
   in `pyproject.toml`; the floor ratchets up as integration tests land).
   Adapter tests use `httpx.MockTransport` / `respx` fixtures — never hit
   live APIs in CI.
5. **Docs are first-class.** Every public class/method needs a docstring with
   at least one runnable example.

## Setting up the dev environment

```bash
git clone https://github.com/datathere/clean-evals
cd clean-evals

python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,postgres]"

# Frontend
cd web && npm install && cd ..

# Local Redis + MySQL (Docker)
docker-compose up -d redis mysql
clean-evals migrate
```

## Running the tests

```bash
# Lint, types, tests
ruff check .
mypy src/
pytest

# Frontend
cd web && npm test && npm run build
```

## Building the wheel locally (with frontend bundled)

```bash
cd web && npm run build && cd ..
python -m build
```

`npm run build` writes the Vite output to `src/clean_evals/web/static/`,
which the wheel packages and `clean-evals serve` reads.

## Pull requests

- Open an issue first for non-trivial changes. Discuss the design before
  writing code.
- Branch from `main`. Keep PRs focused — one concern per PR.
- Conventional commits style for messages (`feat:`, `fix:`, `docs:`, etc.).
- Run `pre-commit run --all-files` before pushing.
- CI must be green: lint, mypy, pytest (all supported Python versions),
  example datasets pass, frontend builds.
- Public API changes require an entry in `CHANGELOG.md` and an update to
  `API.md` with the new stability tag.

## Plugin contributions

Custom scorers / adapters / reporters belong in your own package, not in this
repo. Register them via Python entry points:

```toml
[project.entry-points."clean_evals.scorers"]
my_metric = "your_package.scorers:YourScorer"
```

Two scorers are shipped in-tree because they're foundational
(`exact_match`, `json_field_match`) plus the LLM-judge default. Anything more
specialised should be a separate package.

## Code of conduct

We follow the [Contributor Covenant](CODE_OF_CONDUCT.md). Be excellent to
each other.

## Releasing

Maintainers only. Tag the commit (`v0.x.y`); CI publishes to PyPI and
deploys docs.
