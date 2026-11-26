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


class MonthlyNotionalPool:
    """Candidate C (R8, ``CANDIDATE_LOCK.md`` section 3): a monthly instrument pool by 1-lot notional.

    On the first trading day of each natural month the pool is fixed for the whole month:
    ``pool = { i : N_i <= cap_frac * E }`` with ``N_i = settle_i(last bar of the previous month) * mult_i`` and ``E`` the
    account equity at the previous month's last close (marked to market, costs paid, floating PnL included); the first
    month uses the initial capital.  ``<=``: a 1-lot notional exactly equal to ``cap_frac * E`` is inside the pool.
    A missing / non-positive ``settle`` falls back to that bar's ``close`` (logged in ``report()``); an instrument without
    any bar in the previous month is outside the pool for the month.  Signal day T uses T's calendar month (the T+1 fill may
    fall in the next month).  Already-open positions are never closed by the pool (it only gates new entries).
    """

    def __init__(self, *, equity0: float, mult: dict[str, float], bars: dict[str, list[dict]],
                 cap_frac: float = 0.25, nonferrous: tuple[str, ...] = ("AG", "AL", "AU", "CU", "NI")) -> None:
        self.equity0 = float(equity0)
        self.mult = {str(k): float(v) for k, v in mult.items()}
        self.bars = bars
        self.cap_frac = float(cap_frac)
        self.nonferrous = tuple(nonferrous)
        self._ym: str | None = None
        self._pool: set[str] = set()
        self._months: list[dict] = []
        self._dates = {c: [str(b["date"])[:10] for b in bs] for c, bs in bars.items()}

    def _prev_month_bar(self, code: str, first_day: str) -> dict | None:
        import bisect

        ds = self._dates.get(code) or []
        i = bisect.bisect_left(ds, first_day[:7] + "-01") - 1  # last bar dated before this month
        return self.bars[code][i] if i >= 0 else None

    def begin_day(self, d: str, equity: float) -> None:
        ym = str(d)[:7]
        if ym == self._ym:
            return
        E = self.equity0 if self._ym is None else float(equity)
        pool, excluded, fallback, no_bar = set(), [], [], []
        for code, m in sorted(self.mult.items()):
            b = self._prev_month_bar(code, str(d)) if code in self.bars else None
            if b is None:
                no_bar.append(code)
                continue
            s = b.get("settle")
            try:
                s = float(s) if s is not None else None
            except (TypeError, ValueError):
                s = None
            if s is None or s <= 0:
                s = float(b["close"])
                fallback.append({"code": code, "prev_bar_date": str(b["date"])[:10]})
            n = s * m
            if n <= self.cap_frac * E:
                pool.add(code)
            else:
                excluded.append(code)
        self._ym, self._pool = ym, pool
        self._months.append({"month": ym, "E": E, "pool": sorted(pool), "excluded": excluded, "settle_fallback_close": fallback,
                             "no_prior_bar": no_bar, "nonferrous_in_pool": sorted(set(self.nonferrous) & pool)})

    def allows(self, code: str, d: str) -> bool:
        return str(d)[:7] == self._ym and code in self._pool

    def report(self) -> dict:
        ms = self._months
        return {
            "cap_frac": self.cap_frac,
            "months": ms,
            "months_n": len(ms),
            "months_nonferrous_empty": [m["month"] for m in ms if not m["nonferrous_in_pool"]],
            "settle_fallback_close": [dict(month=m["month"], **x) for m in ms for x in m["settle_fallback_close"]],
        }
