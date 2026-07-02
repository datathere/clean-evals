"""Shared adapter helpers. Internal."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

from clean_evals.errors import (
    ProviderError,
    ProviderTimeout,
    RateLimited,
    SchemaInvalidResponse,
)

_log = logging.getLogger(__name__)


def env_or_raise(var: str) -> str:
    """Return ``os.environ[var]`` or raise a helpful ``ProviderError``."""
    val = os.environ.get(var)
    if not val:
        raise ProviderError(
            f"Environment variable {var!r} is not set.",
            status_code=None,
            body=None,
        )
    return val


def parse_retry_after(header_value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value, returning seconds or ``None``.

    HTTP allows either an integer-seconds value or an HTTP-date. We support
    both, falling back to ``None`` (uncapped backoff) on garbage input.
    """
    if header_value is None:
        return None
    header_value = header_value.strip()
    if not header_value:
        return None
    try:
        return float(header_value)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(header_value)
        return max(0.0, (dt.timestamp() - time.time()))
    except (TypeError, ValueError):
        return None


def reject_floating_alias(model: str) -> None:
    """Defence-in-depth: ``RunConfig`` already rejects, adapters re-check."""
    if model.endswith("-latest") or model == "latest":
        raise ProviderError(
            f"Adapter rejected floating alias {model!r}. Use a dated snapshot id.",
        )


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_s: float,
    provider: str,
) -> tuple[dict[str, Any], int]:
    """POST JSON, mapping errors to clean-evals exception types.

    Returns:
        ``(parsed_response, latency_ms)``.

    Raises:
        ProviderTimeout: On any timeout.
        RateLimited: On HTTP 429 (with parsed ``Retry-After``).
        ProviderError: For any other non-2xx response.
    """
    started = time.perf_counter()
    try:
        resp = await client.post(url, headers=headers, json=payload, timeout=timeout_s)
    except httpx.TimeoutException as exc:
        raise ProviderTimeout(f"{provider} timed out after {timeout_s}s") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"{provider} HTTP error: {exc!r}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)

    if resp.status_code == 429:
        retry_after = parse_retry_after(resp.headers.get("Retry-After"))
        raise RateLimited(
            f"{provider} 429 rate-limited (retry_after={retry_after})",
            retry_after_s=retry_after,
        )
    if resp.status_code >= 400:
        body = resp.text[:1000] if resp.text else None
        raise ProviderError(
            f"{provider} HTTP {resp.status_code}: {body!r}",
            status_code=resp.status_code,
            body=body,
        )

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise ProviderError(
            f"{provider} returned non-JSON body: {resp.text[:200]!r}",
            status_code=resp.status_code,
            body=resp.text[:1000],
        ) from exc
    if not isinstance(data, dict):
        raise ProviderError(
            f"{provider} returned non-object JSON",
            status_code=resp.status_code,
            body=resp.text[:1000],
        )
    return data, latency_ms


def parse_json_or_raise(content: str) -> dict[str, Any]:
    """Try to parse ``content`` as JSON, raising ``SchemaInvalidResponse``.

    Many providers wrap JSON in fenced code blocks; we strip a leading
    ```json``` fence and trailing ``` if present.
    """
    text = content.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaInvalidResponse(
            f"Model returned non-JSON content (first 200 chars): {content[:200]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise SchemaInvalidResponse(
            f"Model returned JSON but not an object: {type(parsed).__name__}"
        )
    return parsed
