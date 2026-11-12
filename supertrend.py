# -*- coding: utf-8 -*-
"""SuperTrend (TradingView-compatible) for daily OHLC.

Matches the shared Pine v4 defaults:
  ATR Period=10, Multiplier=3.0, Source=hl2, Change ATR Method=true (Wilder/RMA ATR).

Trend flip:
  buy  when trend goes -1 → +1 (close crosses above prior down-band)
  sell when trend goes +1 → -1 (close crosses below prior up-band)
"""
from __future__ import annotations

from typing import Any


def _tr(hist: list[dict], i: int) -> float | None:
    if i < 1:
        return None
    try:
        h = float(hist[i]["high"])
        l = float(hist[i]["low"])
        pc = float(hist[i - 1]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    return max(h - l, abs(h - pc), abs(l - pc))


def atr_wilder(hist: list[dict], i: int, n: int = 10) -> float | None:
    """TradingView ``atr(n)`` ≈ Wilder RMA of true range."""
    if i < n or n <= 0:
        return None
    # seed with SMA of first n TRs ending at i-n+1 ... need i >= n
    # Standard: first ATR at index n is SMA of TR[1..n] (n values), then RMA.
    if i == n:
        trs = []
        for j in range(1, n + 1):
            t = _tr(hist, j)
            if t is None:
                return None
            trs.append(t)
        return sum(trs) / n
    prev = atr_wilder(hist, i - 1, n)
    tr = _tr(hist, i)
    if prev is None or tr is None:
        return None
    return (prev * (n - 1) + tr) / n


def atr_wilder_series(hist: list[dict], n: int = 10) -> list[float | None]:
    """O(n) Wilder ATR series (avoid recursive atr_wilder per bar)."""
    out: list[float | None] = [None] * len(hist)
    if len(hist) <= n:
        return out
    trs: list[float] = []
    for j in range(1, len(hist)):
        t = _tr(hist, j)
        if t is None:
            return out
        trs.append(t)
        if j < n:
            continue
        if j == n:
            out[j] = sum(trs[:n]) / n
        else:
            prev = out[j - 1]
            if prev is None:
                continue
            out[j] = (prev * (n - 1) + t) / n
    return out


def supertrend_series(
    hist: list[dict],
    *,
    atr_period: int = 10,
    multiplier: float = 3.0,
    use_wilder_atr: bool = True,
) -> list[dict[str, Any] | None]:
    """Return per-bar dicts: trend (±1), up, dn, buy, sell, atr, src."""
    n = len(hist)
    out: list[dict[str, Any] | None] = [None] * n
    if n < atr_period + 2:
        return out

    if use_wilder_atr:
        atrs = atr_wilder_series(hist, atr_period)
    else:
        atrs = [None] * n
        for i in range(atr_period, n):
            # SMA of last ``atr_period`` TRs ending at i
            vals = []
            ok = True
            for j in range(i - atr_period + 1, i + 1):
                t = _tr(hist, j)
                if t is None:
                    ok = False
                    break
                vals.append(t)
            atrs[i] = sum(vals) / atr_period if ok and vals else None

    up_prev: float | None = None
    dn_prev: float | None = None
    trend_prev = 1

    for i in range(n):
        atr = atrs[i]
        try:
            h = float(hist[i]["high"])
            l = float(hist[i]["low"])
            c = float(hist[i]["close"])
            c1 = float(hist[i - 1]["close"]) if i >= 1 else c
        except (KeyError, TypeError, ValueError):
            continue
        if atr is None or atr <= 0:
            continue
        src = 0.5 * (h + l)  # hl2
        up = src - multiplier * atr
        dn = src + multiplier * atr
        if up_prev is None or dn_prev is None:
            up1, dn1 = up, dn
        else:
            up1, dn1 = up_prev, dn_prev
            # Pine: up := close[1] > up1 ? max(up, up1) : up
            up = max(up, up1) if c1 > up1 else up
            dn = min(dn, dn1) if c1 < dn1 else dn

        trend = trend_prev
        if trend_prev == -1 and c > dn1:
            trend = 1
        elif trend_prev == 1 and c < up1:
            trend = -1

        buy = trend == 1 and trend_prev == -1
        sell = trend == -1 and trend_prev == 1
        out[i] = {
            "trend": trend,
            "up": up,
            "dn": dn,
            "atr": atr,
            "src": src,
            "buy": buy,
            "sell": sell,
            "band": up if trend == 1 else dn,
        }
        up_prev, dn_prev, trend_prev = up, dn, trend
    return out
