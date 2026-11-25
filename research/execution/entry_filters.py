# -*- coding: utf-8 -*-
"""R8b research-only entry filters (pure functions; used by ``historical_backtest.simulate`` when switched on).

Both filters judge a candidate on the close of signal day T (only data dated <= T) and decide whether the
order for T+1 is sent at all.  They are OFF by default and never touch the formal path.

* ``unit_notional_exceeds``  1-lot notional  > ``frac`` x gross-cap amount (account-level cap = sizing equity
  x max_gross_pct / 100, NOT net of the open book).
* ``unit_risk_exceeds``      1-lot stop risk > the per-trade risk budget (``day_risk``).  Under ``min_lots = 0``
  this can never fire (``lots = floor(day_risk / risk_per_lot) >= 1`` already implies it is False);
  it is kept for ``min_lots > 0`` and is not enabled by the R8 CLI.
* ``atr_spike``              ATR14 / ATR100 > ``ratio``; ``None`` (= filter does not fire) when ATR100 is
  not available yet.
"""
from __future__ import annotations

from typing import Any

UNIT_NOTIONAL_FRAC = 0.5
ATR_SPIKE_RATIO = 1.5
ATR_LONG_N = 100


def unit_notional(close: float, mult: float) -> float:
    return float(close) * float(mult)


def gross_cap_amount(sizing_eq: float, max_gross_pct: float) -> float:
    return float(sizing_eq) * float(max_gross_pct) / 100.0


def unit_notional_exceeds(
    close: float,
    mult: float,
    sizing_eq: float,
    max_gross_pct: float,
    frac: float = UNIT_NOTIONAL_FRAC,
) -> bool:
    """Strictly greater: a 1-lot notional of exactly ``frac`` x cap is allowed."""
    return unit_notional(close, mult) > float(frac) * gross_cap_amount(sizing_eq, max_gross_pct)


def unit_risk_exceeds(risk_per_lot: float, day_risk: float) -> bool:
    """Strictly greater: a 1-lot stop risk exactly equal to the budget is allowed."""
    return float(risk_per_lot) > float(day_risk)


def long_atr(adj_series: Any, hist: list[dict], i: int, n: int = ATR_LONG_N) -> float | None:
    """ATR_n on the engine's own series: R6c adjusted (roll-free) when available, raw continuous otherwise.

    ``None`` when fewer than ``n`` bars precede ``i``.  Reads only bars ``<= i``."""
    if adj_series is not None:
        return adj_series.atr_n(i, n)
    if n < 1 or i < n or i >= len(hist):
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        h, l, pc = hist[j]["high"], hist[j]["low"], hist[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / float(n)


def atr_spike(atr_short: float | None, atr_long: float | None, ratio: float = ATR_SPIKE_RATIO) -> bool | None:
    """True / False, or ``None`` when the long ATR is unavailable (the caller must then let the candidate pass)."""
    if atr_short is None or atr_long is None or not atr_long or float(atr_long) <= 0:
        return None
    return float(atr_short) / float(atr_long) > float(ratio)
