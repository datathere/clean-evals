# Writing a custom adapter

Adapters talk to a single model provider. Use them when:

- You're routing through an internal LLM gateway.
- A new provider isn't yet built-in.
- You're stubbing for tests in a separate package.

## Skeleton

```python
from collections.abc import Sequence
from typing import ClassVar, Literal
import httpx
from clean_evals import ModelResponse
from clean_evals.errors import ProviderError, RateLimited
from clean_evals.prompting import ChatMessage

class MyGatewayAdapter:
    provider: ClassVar[str] = "mygateway"

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self, prompt: str, model: str, *,
        temperature: float, seed: int | None, timeout_s: float,
        response_format: Literal["text", "json"] = "text",
        history: Sequence[ChatMessage] | None = None,
    ) -> ModelResponse:
        # history carries prior turns for chat-shaped datasets (cases
        # promoted from transcript telemetry); replay them verbatim before
        # prompt. The runner only passes it when a case has history, so
        # adapters without the parameter keep working for single-shot
        # datasets — but they fail chat cases.
        # ... POST to your gateway, parse the response ...
        ...
```

## Registration

```toml
[project.entry-points."clean_evals.adapters"]
mygateway = "my_pkg.adapters:MyGatewayAdapter"
```

## Pricing

For pricing your adapter's models, either:

- Add entries to your own pricing module and call `compute_cost` yourself
  (then put the value into `ModelResponse.cost_usd`), **or**
- Read cost directly from the provider response (OpenRouter does this).

`clean_evals.pricing` is the source of truth for the table; bump
`PRICING_VERSION` when you change it.
