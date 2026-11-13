# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Sequence


def align_strategy_returns(
    curves: dict[str, Sequence[dict[str, Any]]],
) -> tuple[list[str], list[str], list[list[float]]]:
    """Return (names, dates, T×K simple returns) aligned on shared dates."""
    by_name: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    for name, curve in curves.items():
        prev = None
        m: dict[str, float] = {}
        for row in curve or []:
            if not isinstance(row, dict):
                continue
            d = str(row.get("date") or "")[:10]
            try:
                eq = float(row.get("equity"))
            except (TypeError, ValueError):
                continue
            if prev not in (None, 0) and d:
                m[d] = eq / float(prev) - 1.0
                all_dates.add(d)
            prev = eq
        by_name[str(name)] = m
    names = sorted(by_name)
    dates = sorted(d for d in all_dates if all(d in by_name[n] for n in names))
    mat = [[by_name[n][d] for n in names] for d in dates]
    return names, dates, mat
