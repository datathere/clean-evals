"""Tests for percentile / mean / median helpers."""

from __future__ import annotations

import pytest

from clean_evals._internal.stats import mean, median, percentile


def test_mean_empty_zero() -> None:
    assert mean([]) == 0.0


def test_mean_basic() -> None:
    assert mean([1, 2, 3]) == 2


def test_median_odd() -> None:
    assert median([1, 2, 3]) == 2


def test_median_even() -> None:
    assert median([1, 2, 3, 4]) == 2.5


def test_median_empty() -> None:
    assert median([]) == 0.0


def test_percentile_endpoints() -> None:
    assert percentile([1, 2, 3, 4, 5], 0) == 1
    assert percentile([1, 2, 3, 4, 5], 100) == 5


def test_percentile_50_is_median() -> None:
    assert percentile([1, 2, 3, 4, 5], 50) == 3


def test_percentile_invalid() -> None:
    with pytest.raises(ValueError):
        percentile([1], 110)


def test_percentile_empty_zero() -> None:
    assert percentile([], 95) == 0.0
