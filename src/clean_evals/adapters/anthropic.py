"""Anthropic Messages API adapter.

Targets the public ``/v1/messages`` endpoint. Uses ``ANTHROPIC_API_KEY``.

The adapter does not configure prompt caching automatically — callers who
want caching add the ``cache_control`` blocks themselves through a custom
adapter wrapper. clean-evals stays opinionated about evaluation, not about
how each prompt is shaped.
"""

from __future__ import annotations

import logging
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

_log = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnthropicAdapter:
    """Adapter for Anthropic ``claude-*`` snapshots."""

    provider: ClassVar[str] = "anthropic"

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
        """Close the underlying HTTP client if owned by this adapter."""
        if self._owned_client:
            await self._client.aclose()

    async def complete(
        self,
        prompt: str,
        model: str,
        *,
        temperature: float,
        seed: int | None,  # noqa: ARG002 — Anthropic ignores seed; kept for protocol
        timeout_s: float,
        response_format: Literal["text", "json"] = "text",
        system: str | None = None,
        reasoning_effort: str | None = None,  # noqa: ARG002 — not exposed by this API
        max_output_tokens: int | None = None,
    ) -> ModelResponse:
        reject_floating_alias(model)
        api_key = self._api_key or env_or_raise("ANTHROPIC_API_KEY")

        headers = {
            "x-api-key": api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        system_parts = [system] if system else []
        if response_format == "json":
            system_parts.append(
                "Return ONLY a valid JSON object. Do not wrap it in code fences "
                "or include any prose. Top-level value must be an object."
            )

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_output_tokens or 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if capabilities(self.provider, model).supports_temperature:
            payload["temperature"] = temperature
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

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
            # Newer models reject temperature outright. Retry once without
            # it so models the capability rules do not know yet still run.
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
        usage = data.get("usage", {})
        tokens_in = int(usage.get("input_tokens", -1))
        tokens_out = int(usage.get("output_tokens", -1))

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
    """Pull the assistant text out of the Anthropic response envelope."""
    pieces: list[str] = []
    for block in data.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces)
