"""Exception types raised by the runner and adapters.

All exceptions inherit from :class:`CleanEvalsError`. Tests can opt in with
``pytest.raises(CleanEvalsError)`` to catch the family.

The runner translates these into ``CaseResult.status`` values; user code
should rarely catch them directly.
"""

from __future__ import annotations


class CleanEvalsError(Exception):
    """Base class for every clean-evals exception."""


class ConfigError(CleanEvalsError):
    """Raised when a config value fails validation outside Pydantic.

    Pydantic validation failures surface as ``pydantic.ValidationError``
    directly; this is for cross-field or cross-source checks.
    """


class AdapterError(CleanEvalsError):
    """Base class for adapter-layer errors."""


class RateLimited(AdapterError):
    """Provider returned 429.

    Attributes:
        retry_after_s: Suggested wait, derived from the ``Retry-After`` header.
            ``None`` if the header was absent or unparseable.
    """

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderTimeout(AdapterError):
    """The provider took longer than the per-call timeout."""


class ProviderError(AdapterError):
    """Provider returned a non-2xx response that isn't 429.

    Attributes:
        status_code: HTTP status code, or ``None`` for non-HTTP errors.
        body: Truncated response body for debugging.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class SchemaInvalidResponse(AdapterError):
    """Provider returned text but ``response_format="json"`` was requested.

    Surfaces as ``CaseResult.status="schema_invalid"``.
    """


class CostCeilingExceeded(CleanEvalsError):
    """Run aborted because cumulative cost reached ``RunConfig.max_cost_usd``."""


class DailyCostLimitExceeded(CleanEvalsError):
    """Run refused to start because the daily spend limit is already reached."""


class UnknownPlugin(CleanEvalsError):
    """A scorer / adapter / reporter name was requested but not registered."""
