# -*- coding: utf-8 -*-
"""Single EMA crossover (TradingView ``Backtest single EMA cross`` port).

Defaults: EMA(close,10) vs EMA(close,20).
  long  on crossover(ema10, ema20)
  short on crossunder(ema10, ema20)
"""
from __future__ import annotations

from typing import Any


def ema_series(closes: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if n <= 0 or len(closes) < n:
        return out
    k = 2 / (n + 1)
    # seed = SMA of first n closes
    seed = sum(closes[:n]) / n
    out[n - 1] = seed
    v = seed
    for i in range(n, len(closes)):
        v = closes[i] * k + v * (1 - k)
        out[i] = v
    return out


def ema_cross_series(
    hist: list[dict],
    *,
    fast: int = 10,
    slow: int = 20,
) -> list[dict[str, Any] | None]:
    """Per-bar: ema_fast, ema_slow, long (crossover), short (crossunder)."""
    n = len(hist)
    out: list[dict[str, Any] | None] = [None] * n
    if n < slow + 1:
        return out
    closes: list[float] = []
    for b in hist:
        try:
            closes.append(float(b["close"]))
        except (KeyError, TypeError, ValueError):
            closes.append(float("nan"))
    f = ema_series(closes, fast)
    s = ema_series(closes, slow)
    for i in range(1, n):
        e0, e1 = f[i], f[i - 1]
        m0, m1 = s[i], s[i - 1]
        if None in (e0, e1, m0, m1):
            continue
        # crossover: prev fast<=slow and now fast>slow
        long = e1 <= m1 and e0 > m0
        short = e1 >= m1 and e0 < m0
        out[i] = {
            "ema_fast": e0,
            "ema_slow": m0,
            "long": long,
            "short": short,
        }
    return out
