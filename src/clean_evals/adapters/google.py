"""Google Generative Language (Gemini) adapter.

Uses ``generativelanguage.googleapis.com/v1beta/models/{model}:generateContent``
authenticated via the ``x-goog-api-key`` header. Header auth keeps the key
out of URLs, which end up in exception messages, logs, and stored errors.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Literal

import httpx

from clean_evals.adapters._base import (
    env_or_raise,
    parse_json_or_raise,
    post_json,
    reject_floating_alias,
)
from clean_evals.models import ModelResponse
from clean_evals.pricing import compute_cost
from clean_evals.prompting import ChatMessage

_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GoogleAdapter:
    provider: ClassVar[str] = "google"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url_template: str = _API_URL_TEMPLATE,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_url_template = api_url_template
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
        seed: int | None,  # noqa: ARG002 — Gemini doesn't expose user-facing seeds
        timeout_s: float,
        response_format: Literal["text", "json"] = "text",
        system: str | None = None,
        reasoning_effort: str | None = None,  # noqa: ARG002 — not exposed by this API
        max_output_tokens: int | None = None,
        history: Sequence[ChatMessage] | None = None,
    ) -> ModelResponse:
        reject_floating_alias(model)
        api_key = self._api_key or env_or_raise("GOOGLE_API_KEY")

        url = self._api_url_template.format(model=model)
        generation_config: dict[str, Any] = {"temperature": temperature}
        if max_output_tokens is not None:
            generation_config["maxOutputTokens"] = max_output_tokens
        if response_format == "json":
            generation_config["responseMimeType"] = "application/json"

        # Gemini's assistant role is "model".
        contents: list[dict[str, Any]] = [
            {
                "role": "model" if turn["role"] == "assistant" else "user",
                "parts": [{"text": turn["content"]}],
            }
            for turn in history or ()
        ]
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        data, latency_ms = await post_json(
            self._client,
            url,
            headers={"content-type": "application/json", "x-goog-api-key": api_key},
            payload=payload,
            timeout_s=timeout_s,
            provider=self.provider,
        )

        content = _extract_text(data)
        usage = data.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount", -1))
        tokens_out = int(usage.get("candidatesTokenCount", -1))

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
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    pieces: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces)
