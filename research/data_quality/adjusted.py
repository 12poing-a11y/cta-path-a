# -*- coding: utf-8 -*-
"""Roll-free signal series (R6c).

Signals (r20 / r60), ATR14 and the volatility used by ``vol_bypass`` must not see the
calendar-spread jump a continuous contract shows on a main-contract roll day.  We do NOT
build a back-adjusted *price level* (that needs the future roll factors); instead every
day gets a self-contained quantity that only depends on data dated <= that day:

* roll-free return  ``ret[d]``
    - normal day            : ``close_d / close_{d-1} - 1`` of the continuous contract
    - roll day (main_map[d] != main_map[d-1], both known):
      ``C_d(new) / C_{d-1}(new) - 1`` with both closes from the NEW main contract itself.
* same-contract true range ``tr[d] = max(H_d - L_d, |H_d - C*_{d-1}|, |L_d - C*_{d-1}|)``
  where ``C*_{d-1}`` is d's main contract's own close on d-1 (identical to the continuous
  close on non-roll days).
* ``ret_n(i, n)``  = product of the last n roll-free returns - 1  (percent, like the raw one)
* ``atr14(i)``     = mean of the last 14 ``tr``

Whenever a needed price is missing (``main_map`` unknown on d or d-1, or the new
contract's d-1 close cannot be found) that day falls back to the raw continuous
definition and is counted (``adj_fallback_days``).

Truncation safety: ``ret[d]`` / ``tr[d]`` are computed from bars <= d only
(``main_map[d]`` itself uses only day-d data and ``main_map[d-1]``); no quantity is
anchored on later bars, so cutting the history at T never changes anything at <= T.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research.data_quality.main_map import MainMap
from research.data_quality.rolls import is_roll_day, load_contract_bar

ROOT = Path(__file__).resolve().parents[2]


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


@dataclass
class AdjustedSeries:
    code: str
    hist: list[dict]
    ret: list[float | None]  # roll-free 1-day return, index-aligned with hist (ret[0] is None)
    tr: list[float | None]  # same-contract true range
    roll: list[bool]  # actual main roll on this day
    fallback: list[bool]  # raw continuous definition used on this day
    _adj_cnt: list[int] = field(default_factory=list)  # prefix count of (roll or fallback) days
    _level: list[float] | None = None

    # ---- accessors -------------------------------------------------------------
    def _window_clean(self, lo: int, hi: int) -> bool:
        """True when days lo+1..hi contain neither a roll nor a fallback day."""
        return self._adj_cnt[hi] - self._adj_cnt[lo] == 0

    def ret_n(self, i: int, n: int) -> float | None:
        """Percent return over the last n sessions with roll days replaced by roll-free returns."""
        if i < n or i >= len(self.hist):
            return None
        if self._window_clean(i - n, i):
            a, b = self.hist[i - n]["close"], self.hist[i]["close"]
            if not a:
                return None
            return (b / a - 1.0) * 100.0
        acc = 1.0
        for j in range(i - n + 1, i + 1):
            r = self.ret[j]
            if r is None:
                return None
            acc *= 1.0 + r
        return (acc - 1.0) * 100.0

    def atr14(self, i: int) -> float | None:
        if i < 14 or i >= len(self.hist):
            return None
        if self._window_clean(i - 14, i):
            trs = []
            for j in range(i - 13, i + 1):
                h, l, pc = self.hist[j]["high"], self.hist[j]["low"], self.hist[j - 1]["close"]
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            return sum(trs) / 14.0
        vals = []
        for j in range(i - 13, i + 1):
            t = self.tr[j]
            if t is None:
                return None
            vals.append(t)
        return sum(vals) / 14.0

    def vol_hist(self) -> list[dict]:
        """Bars carrying a roll-free close *index* (forward-built, so truncation-safe).

        ``vol_factor_combo`` only needs 1-day close ratios; ratios of this index equal
        the roll-free returns.  Real prices are never read from it."""
        if self._level is None:
            lv: list[float] = []
            cur = None
            for j, b in enumerate(self.hist):
                if j == 0 or cur is None:
                    cur = float(b["close"])
                else:
                    r = self.ret[j]
                    cur = cur * (1.0 + r) if r is not None else float(b["close"])
                lv.append(cur)
            self._level = lv
        return [
            {"date": b.get("date"), "close": self._level[j]} for j, b in enumerate(self.hist)
        ]

    def fallback_days(self, since: str | None = None) -> int:
        return sum(
            1
            for j, f in enumerate(self.fallback)
            if f and (since is None or str(self.hist[j].get("date") or "")[:10] >= since)
        )

    def roll_days(self, since: str | None = None) -> int:
        return sum(
            1
            for j, f in enumerate(self.roll)
            if f and (since is None or str(self.hist[j].get("date") or "")[:10] >= since)
        )


def build_adjusted_series(
    code: str,
    hist: list[dict],
    main_map: MainMap | None,
    *,
    root: Path | None = None,
) -> AdjustedSeries:
    root = root or ROOT  # root path or ContractStore
    n = len(hist)
    ret: list[float | None] = [None] * n
    tr: list[float | None] = [None] * n
    roll = [False] * n
    fb = [False] * n
    for j in range(1, n):
        b, p = hist[j], hist[j - 1]
        d = str(b.get("date") or "")[:10]
        d0 = str(p.get("date") or "")[:10]
        c1, c0 = _f(b.get("close")), _f(p.get("close"))
        h1, l1 = _f(b.get("high")), _f(b.get("low"))
        raw_ret = (c1 / c0 - 1.0) if (c1 is not None and c0) else None
        raw_tr = None
        if None not in (h1, l1, c0):
            raw_tr = max(h1 - l1, abs(h1 - c0), abs(l1 - c0))
        m1 = main_map.main(code, d) if main_map is not None else None
        m0 = main_map.main(code, d0) if main_map is not None else None
        if m1 is None or m0 is None:
            ret[j], tr[j], fb[j] = raw_ret, raw_tr, True
            continue
        if not is_roll_day(m0, m1):
            ret[j], tr[j] = raw_ret, raw_tr
            continue
        roll[j] = True
        new_prev = load_contract_bar(m1, d0, root=root, snap_bar=p)
        new_cur = load_contract_bar(m1, d, root=root, snap_bar=b)
        pc = _f(new_prev["close"]) if new_prev else None
        cc = _f(new_cur["close"]) if new_cur else c1  # matched within one tick by main_map
        if pc is None or not pc or cc is None:
            ret[j], tr[j], fb[j] = raw_ret, raw_tr, True
            continue
        ret[j] = cc / pc - 1.0
        if h1 is None or l1 is None:
            tr[j] = raw_tr
            fb[j] = True
        else:
            tr[j] = max(h1 - l1, abs(h1 - pc), abs(l1 - pc))
    cnt = [0] * n
    for j in range(1, n):
        cnt[j] = cnt[j - 1] + (1 if (roll[j] or fb[j]) else 0)
    return AdjustedSeries(code=code, hist=hist, ret=ret, tr=tr, roll=roll, fallback=fb, _adj_cnt=cnt)


def build_adjusted_pack(
    series: dict[str, dict[str, Any]],
    main_map: MainMap | None,
    *,
    root: Path | None = None,
) -> dict[str, AdjustedSeries]:
    return {
        code: build_adjusted_series(code, pack.get("hist") or [], main_map, root=root)
        for code, pack in series.items()
    }
