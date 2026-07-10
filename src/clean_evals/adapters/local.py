"""Local / OpenAI-compatible endpoint adapter.

One adapter covers the local-inference ecosystem: Ollama, LM Studio,
llama.cpp server, vLLM, LocalAI, and any other server that exposes the
OpenAI-compatible ``/chat/completions`` API. Hosted OpenAI-compatible
gateways work the same way.

Model ids carry a ``local/`` prefix (``local/llama3.2``,
``local/qwen2.5-coder:14b``); the prefix routes the call here and is
stripped before the request is sent. The dated-snapshot rule does not
apply to this provider — a local model is pinned by the file on disk.

Configuration:

- ``CLEAN_EVALS_LOCAL_BASE_URL`` — the server's OpenAI-compatible base
  URL. Default: ``http://localhost:11434/v1`` (Ollama).
- ``CLEAN_EVALS_LOCAL_API_KEY`` — optional bearer token; some servers
  (vLLM with ``--api-key``, hosted gateways) require one.

Cost is computed from the pricing table, which has no entries for local
models — so it is $0.00 unless an override is configured (for example to
account for hardware or hosted-gateway cost).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, ClassVar, Literal

import httpx

from clean_evals.adapters._base import parse_json_or_raise, post_json
from clean_evals.models import ModelResponse
from clean_evals.pricing import compute_cost
from clean_evals.prompting import ChatMessage

DEFAULT_BASE_URL = "http://localhost:11434/v1"

MODEL_PREFIX = "local/"

_BASE_URL_ENV = "CLEAN_EVALS_LOCAL_BASE_URL"
_API_KEY_ENV = "CLEAN_EVALS_LOCAL_API_KEY"


def strip_prefix(model: str) -> str:
    """The model id as the local server knows it (``local/`` removed)."""
    return model.removeprefix(MODEL_PREFIX)


class LocalAdapter:
    provider: ClassVar[str] = "local"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient()

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    def _resolved_base_url(self) -> str:
        env = os.environ.get(_BASE_URL_ENV, "").strip()
        return (self._base_url or env or DEFAULT_BASE_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        api_key = self._api_key or os.environ.get(_API_KEY_ENV, "").strip()
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        return headers

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
        reasoning_effort: str | None = None,  # noqa: ARG002 — not standardised locally
        max_output_tokens: int | None = None,
        history: Sequence[ChatMessage] | None = None,
    ) -> ModelResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for turn in history or ():
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": strip_prefix(model),
            "messages": messages,
            "temperature": temperature,
        }
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        if seed is not None:
            payload["seed"] = seed
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        data, latency_ms = await post_json(
            self._client,
            f"{self._resolved_base_url()}/chat/completions",
            headers=self._headers(),
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
