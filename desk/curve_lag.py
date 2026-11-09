# -*- coding: utf-8 -*-
"""Equity-curve freshness helpers (display only; never fabricates bars)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from desk.loaders import equity_curve_df


def curve_end_date(payload: dict[str, Any] | None) -> str | None:
    """Last real curve date (ISO) from payload equity_curve, else payload end."""
    df = equity_curve_df(payload)
    if not df.empty:
        return str(df["date"].max().date())
    if payload:
        end = str(payload.get("end") or "")[:10]
        if len(end) == 10:
            return end
    return None


def curve_lag(curve_end: str | None, expected: str) -> dict[str, Any]:
    """Calendar + business-day lag of ``curve_end`` vs expected session date."""
    out: dict[str, Any] = {
        "curve_end": curve_end,
        "expected": expected,
        "lag_days": None,
        "lag_busdays": None,
        "stale": False,
    }
    if not curve_end:
        return out
    try:
        ce = pd.Timestamp(curve_end).normalize()
        ex = pd.Timestamp(expected).normalize()
    except (TypeError, ValueError):
        return out
    cal = max((ex - ce).days, 0)
    bus = int(np.busday_count(ce.date(), ex.date())) if ex > ce else 0
    out.update(lag_days=cal, lag_busdays=bus, stale=bus > 0)
    return out
