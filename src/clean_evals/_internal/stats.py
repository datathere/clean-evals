"""Pure summary statistics. Internal."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def mean(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def median(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    sorted_xs = sorted(xs)
    n = len(sorted_xs)
    mid = n // 2
    if n % 2 == 1:
        return sorted_xs[mid]
    return (sorted_xs[mid - 1] + sorted_xs[mid]) / 2


def percentile(xs: Iterable[float], p: float) -> float:
    """Linear-interpolation percentile.

    ``p`` is in the range 0–100. Empty input returns ``0.0``.
    """
    if not 0.0 <= p <= 100.0:
        raise ValueError("percentile p must be between 0 and 100")
    sorted_xs = sorted(xs)
    n = len(sorted_xs)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_xs[0])
    rank = (p / 100.0) * (n - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(sorted_xs[lo])
    frac = rank - lo
    return float(sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac)
