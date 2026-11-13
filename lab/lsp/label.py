# -*- coding: utf-8 -*-
"""Label LSP outcomes after the pierce bar (research labels; not fill signals)."""
from __future__ import annotations

from typing import Any, Sequence

from lab.lsp.schema import SWEEP_OUTCOMES


def label_events(
    bars: Sequence[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    *,
    reclaim_bars: int = 5,
    horizons: tuple[int, ...] = (1, 3, 5, 10),
) -> list[dict[str, Any]]:
    """Classify fake_break_reversal / true_break_continuation / invalid_sweep."""
    n = len(bars)
    out: list[dict[str, Any]] = []
    for raw in events:
        ev = dict(raw)
        i = int(ev.get("bar_index") or -1)
        if i < 0 or i >= n:
            ev["outcome"] = None
            out.append(ev)
            continue
        level = float(ev["level_price"])
        direction = ev.get("break_direction")
        pierce_close = float(bars[i]["close"])
        # Forward path
        mfe = 0.0
        mae = 0.0
        reclaim_at = None
        outside_hold = 0
        for k in range(1, max(reclaim_bars, max(horizons)) + 1):
            j = i + k
            if j >= n:
                break
            h = float(bars[j]["high"])
            l = float(bars[j]["low"])
            c = float(bars[j]["close"])
            if direction == "up":
                mfe = max(mfe, h - pierce_close)
                mae = max(mae, pierce_close - l)
                if c < level and reclaim_at is None and k <= reclaim_bars:
                    reclaim_at = k
                if c > level:
                    outside_hold += 1
            else:
                mfe = max(mfe, pierce_close - l)
                mae = max(mae, h - pierce_close)
                if c > level and reclaim_at is None and k <= reclaim_bars:
                    reclaim_at = k
                if c < level:
                    outside_hold += 1

        # Horizons: signed return from pierce close
        for h in horizons:
            j = i + h
            key = f"post_sweep_return_{h}"
            if j < n:
                c = float(bars[j]["close"])
                if direction == "up":
                    ev[key] = round((c - pierce_close) / pierce_close, 6)
                else:
                    ev[key] = round((pierce_close - c) / pierce_close, 6)
            else:
                ev[key] = None

        atr = float(ev.get("atr") or 0) or 1.0
        ev["reclaim_bars"] = reclaim_at
        ev["mfe"] = round(mfe / atr, 4)
        ev["mae"] = round(mae / atr, 4)
        ev["outside_hold_bars"] = outside_hold

        # Decision rules (explicit, tunable later)
        if reclaim_at is not None and reclaim_at <= reclaim_bars and (mfe / atr) < 1.5:
            outcome = "fake_break_reversal"
        elif outside_hold >= max(2, reclaim_bars // 2) and reclaim_at is None:
            outcome = "true_break_continuation"
        elif reclaim_at is None and (mfe / atr) >= 0.8:
            outcome = "true_break_continuation"
        else:
            outcome = "invalid_sweep"
        assert outcome in SWEEP_OUTCOMES
        ev["outcome"] = outcome
        out.append(ev)
    return out
