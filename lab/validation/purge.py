# -*- coding: utf-8 -*-
"""Purge / embargo helpers for event ML (Lopez de Prado style, research only)."""
from __future__ import annotations

from typing import Any, Sequence


def time_split_with_purge(
    n: int,
    *,
    oos_frac: float = 0.3,
    purge: int = 10,
    embargo: int = 5,
) -> dict[str, Any]:
    """Chronological train/test indices with purge+embargo around the cut.

    Train uses ``[0, cut)`` then drops the last ``purge`` samples (whose label
    horizon would overlap the test window). Embargo drops the first ``embargo``
    samples of the test side (or equivalently gaps after cut).
    """
    if n < 20:
        return {"ok": False, "error": "too_short", "n": n}
    cut = max(1, int(n * (1.0 - oos_frac)))
    if cut >= n:
        cut = n - 1
    purge = max(0, int(purge))
    embargo = max(0, int(embargo))
    train_end = max(0, cut - purge)
    test_start = min(n, cut + embargo)
    tr = list(range(0, train_end))
    te = list(range(test_start, n))
    if len(tr) < 20 or len(te) < 10:
        return {
            "ok": False,
            "error": "purge_left_insufficient",
            "n": n,
            "n_train": len(tr),
            "n_oos": len(te),
            "cut": cut,
            "purge": purge,
            "embargo": embargo,
        }
    return {
        "ok": True,
        "train_idx": tr,
        "test_idx": te,
        "cut": cut,
        "purge": purge,
        "embargo": embargo,
        "n_train": len(tr),
        "n_oos": len(te),
        "n_purged": cut - train_end,
        "n_embargoed": test_start - cut,
    }


def average_rank(values: Sequence[float], *, higher_is_better: bool = True) -> list[float]:
    """Competition-style average ranks for ties (1=best when higher_is_better)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i], reverse=higher_is_better)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # ranks i..j are tied → average of (i+1)..(j+1)
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks
