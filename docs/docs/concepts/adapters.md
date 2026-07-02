# Adapters

Adapters talk to a single model provider. Built-in: Anthropic, OpenAI,
Google, OpenRouter.

```python
class ModelAdapter(Protocol):
    provider: ClassVar[str]
    async def complete(
        self, prompt: str, model: str, *,
        temperature: float, seed: int | None,
        timeout_s: float, response_format: Literal["text", "json"] = "text",
    ) -> ModelResponse: ...
```

## Adapter responsibilities

- **Async-native.** Use `httpx.AsyncClient`. Never `requests`.
- **Reject floating aliases.** `RunConfig` already rejects `-latest`; the
  adapter should defend in depth.
- **Populate cost.** Use `clean_evals.pricing.compute_cost` against the
  prompt's actual token counts. OpenRouter (which proxies to dozens of
  upstreams) takes its cost from the provider response.
- **Surface 429s clearly.** Raise `RateLimited` with the parsed
  `Retry-After` value so the runner can back off.
- **Use the defined exception types.** `ProviderTimeout`, `ProviderError`,
  `SchemaInvalidResponse`. Defined in `clean_evals.errors`.

## Provider auth

Adapters read keys directly from env vars (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, …). The runner does not pass them through.
