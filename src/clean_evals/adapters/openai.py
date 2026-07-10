"""OpenAI Chat Completions adapter.

Uses ``/v1/chat/completions`` with ``OPENAI_API_KEY``. Supports
``response_format={"type": "json_object"}`` natively for JSON mode.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, ClassVar, Literal

import httpx

from clean_evals.adapters._base import (
    env_or_raise,
    parse_json_or_raise,
    post_json,
    reject_floating_alias,
)
from clean_evals.capabilities import capabilities
from clean_evals.errors import ProviderError
from clean_evals.models import ModelResponse
from clean_evals.pricing import compute_cost
from clean_evals.prompting import ChatMessage

_log = logging.getLogger(__name__)

_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIAdapter:
    provider: ClassVar[str] = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str = _API_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
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
        history: Sequence[ChatMessage] | None = None,
    ) -> ModelResponse:
        reject_floating_alias(model)
        api_key = self._api_key or env_or_raise("OPENAI_API_KEY")

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for turn in history or ():
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        # Reasoning models (o1, o3, ...) reject temperature.
        if capabilities(self.provider, model).supports_temperature:
            payload["temperature"] = temperature
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        if max_output_tokens is not None:
            payload["max_completion_tokens"] = max_output_tokens
        if seed is not None:
            payload["seed"] = seed
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
            # Reasoning-only models (o1, o1-mini) restrict some params; harmless
            # for chat models and required by JSON mode.

        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        try:
            data, latency_ms = await post_json(
                self._client,
                self._api_url,
                headers=headers,
                payload=payload,
                timeout_s=timeout_s,
                provider=self.provider,
            )
        except ProviderError as exc:
            # Model families the capability rules do not know yet may
            # reject temperature. Retry once without it.
            rejected_temperature = (
                exc.status_code == 400 and "temperature" in str(exc) and "temperature" in payload
            )
            if not rejected_temperature:
                raise
            _log.info("%s rejected temperature; retrying without it", model)
            del payload["temperature"]
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

        parsed: dict[str, Any] | None = None
        if response_format == "json":
            parsed = parse_json_or_raise(content)

        return ModelResponse(
            content=content,
            parsed=parsed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_usd=compute_cost(
                self.provider, model, tokens_in=max(tokens_in, 0), tokens_out=max(tokens_out, 0)
            ),
            raw=data,
        )


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    return content if isinstance(content, str) else ""
