"""OpenRouter adapter — proxy to dozens of providers behind one HTTP API.

Wire-compatible with OpenAI's chat completions, plus an OpenRouter-specific
``HTTP-Referer`` and ``X-Title`` for usage attribution.

Pricing is delegated to OpenRouter when present in the response — the
upstream cost varies by route and we don't ship a complete table for every
backend OpenRouter brokers.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

import httpx

from clean_evals.adapters._base import (
    env_or_raise,
    parse_json_or_raise,
    post_json,
)
from clean_evals.models import ModelResponse

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_REFERER = "https://github.com/datathere/clean-evals"
_DEFAULT_TITLE = "clean-evals"


class OpenRouterAdapter:
    provider: ClassVar[str] = "openrouter"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str = _API_URL,
        referer: str = _DEFAULT_REFERER,
        title: str = _DEFAULT_TITLE,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._referer = referer
        self._title = title
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient()

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def complete(
        self,
        prompt: str,
        model: str,
        *,
        temperature: float,
        seed: int | None,
        timeout_s: float,
        response_format: Literal["text", "json"] = "text",
        system: str | None = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelResponse:
        # OpenRouter passes the model id straight through to the upstream
        # provider. We don't reject "-latest" here because OpenRouter
        # offers genuine "stable channel" labels for some models. Users who
        # want determinism stick to dated snapshots in their config.
        api_key = self._api_key or env_or_raise("OPENROUTER_API_KEY")

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if reasoning_effort is not None:
            payload["reasoning"] = {"effort": reasoning_effort}
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        if seed is not None:
            payload["seed"] = seed
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "HTTP-Referer": self._referer,
            "X-Title": self._title,
        }

        data, latency_ms = await post_json(
            self._client,
            self._api_url,
            headers=headers,
            payload=payload,
            timeout_s=timeout_s,
            provider=self.provider,
        )

        content = _extract_text(data)
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", -1))
        tokens_out = int(usage.get("completion_tokens", -1))

        # OpenRouter sometimes returns total cost directly. Trust that when
        # present — it's authoritative per their billing.
        cost_usd = float(usage.get("total_cost", 0.0) or 0.0)

        parsed: dict[str, Any] | None = None
        if response_format == "json":
            parsed = parse_json_or_raise(content)

        return ModelResponse(
            content=content,
            parsed=parsed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            raw=data,
        )


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    return content if isinstance(content, str) else ""
