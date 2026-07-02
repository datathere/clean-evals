# Adapters

Adapters talk to a single model provider. Built-in: Anthropic, OpenAI,
Google, OpenRouter, and Local (OpenAI-compatible endpoints).

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

## Local models (Ollama, LM Studio, llama.cpp, vLLM, ...)

The `local` adapter talks to any server that exposes the
OpenAI-compatible `/chat/completions` API — which covers the local
inference ecosystem and hosted OpenAI-compatible gateways.

Model ids carry a `local/` prefix; the prefix routes the call and is
stripped before the request is sent:

```bash
export CLEAN_EVALS_LOCAL_BASE_URL=http://localhost:11434/v1   # Ollama default
clean-evals run dataset.yml --models local/llama3.2,gpt-4o-mini-2024-07-18
```

Configuration:

| Env var | Meaning | Default |
| ------- | ------- | ------- |
| `CLEAN_EVALS_LOCAL_BASE_URL` | The server's OpenAI-compatible base URL | `http://localhost:11434/v1` |
| `CLEAN_EVALS_LOCAL_API_KEY`  | Optional bearer token (vLLM `--api-key`, gateways) | unset |

Notes:

- The dated-snapshot rule does not apply to `local/` models — a local
  model is pinned by the file on disk, so tags like
  `local/llama3.2:latest` are valid.
- Cost is $0.00 unless you add a pricing override for the model (for
  example to account for gateway or hardware cost).
- When the base URL is set, the Models page probes `GET /models` on the
  server and lists the installed models alongside the hosted providers.
