# -*- coding: utf-8 -*-
"""Session / rolling VWAP as additional LSP key levels."""
from __future__ import annotations

from typing import Any, Sequence

from lab.lsp.levels import SwingLevel


def rolling_vwap(bars: Sequence[dict[str, Any]], window: int = 20) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    for i in range(len(bars)):
        j0 = max(0, i - window + 1)
        num = 0.0
        den = 0.0
        for j in range(j0, i + 1):
            b = bars[j]
            try:
                tp = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
                vol = float(b.get("volume") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            num += tp * vol
            den += vol
        out[i] = (num / den) if den > 0 else None
    return out


def vwap_levels_as_swings(
    bars: Sequence[dict[str, Any]],
    *,
    window: int = 20,
    every: int = 10,
) -> list[SwingLevel]:
    """Sample rolling VWAP as soft levels (confirmed at sample bar)."""
    vw = rolling_vwap(bars, window=window)
    out: list[SwingLevel] = []
    for i, v in enumerate(vw):
        if v is None or i < window:
            continue
        if i % every != 0:
            continue
        ts = str(bars[i].get("datetime") or bars[i].get("date") or "")
        # Treat as both approach magnets: use kind high/low by side later via price vs close
        close = float(bars[i]["close"])
        kind = "high" if v >= close else "low"
        out.append(SwingLevel(kind, i, float(v), i, ts or None))
    return out
