# Writing a custom reporter

Reporters write a `RunResult` to a destination. The default trio
(`markdown`, `jsonl`, `junit`) plus `console` covers the common cases.

Examples of valid custom reporters:

- Push results to a Slack channel.
- Upload to a BI tool.
- Open a GitHub PR comment.
- Insert into a domain-specific data warehouse.

## Skeleton

```python
from pathlib import Path
from typing import ClassVar
from clean_evals.models import RunResult

class SlackReporter:
    name: ClassVar[str] = "slack"

    def __init__(self, *, webhook: str | None = None) -> None:
        self._webhook = webhook

    def write(self, result: RunResult, output_dir: Path) -> Path:
        # ... post to Slack ...
        # Return the primary artifact path. If you don't write anything to
        # disk, return ``output_dir`` itself.
        return output_dir
```

## Synchronous

Reporters run synchronously after the run completes. Do not perform
long-running work — if you need to ship to S3 / Slack / etc., use the
runner's `event_sink` for the live path or queue work via Celery from inside
your reporter and return immediately.
