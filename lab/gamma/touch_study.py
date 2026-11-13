# -*- coding: utf-8 -*-
"""Price vs wall touch / pierce / bounce study on daily futures path."""
from __future__ import annotations

from typing import Any, Sequence

from gamma_wall import load_history


def _atr(hist: Sequence[dict], i: int, n: int = 14) -> float | None:
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        h, l, c = float(hist[j]["high"]), float(hist[j]["low"]), float(hist[j]["close"])
        pc = float(hist[j - 1]["close"]) if j > 0 else c
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n if trs else None


def touch_event_study(
    contract: str,
    daily_bars: Sequence[dict[str, Any]],
    *,
    touch_atr: float = 1.0,
    horizons: tuple[int, ...] = (1, 3, 5),
    root=None,
) -> dict[str, Any]:
    """When close is within touch_atr of call/put wall, label bounce/pierce/stay."""
    snaps = load_history(contract, root=root)
    by_date = {str(s["asof"])[:10]: s for s in snaps}
    # index daily
    idx = {str(b.get("date") or b.get("datetime") or "")[:10]: i for i, b in enumerate(daily_bars)}
    events = []
    for d, snap in sorted(by_date.items()):
        i = idx.get(d)
        if i is None:
            continue
        atr = _atr(daily_bars, i)
        if atr is None or atr <= 0:
            continue
        fp = float(snap["futures_price"] or daily_bars[i]["close"])
        for side, wall_key in (("call", "call_wall"), ("put", "put_wall")):
            wall = float(snap[wall_key])
            dist = (fp - wall) / atr
            if abs(dist) > touch_atr:
                continue
            # Forward path
            outcome = "stay"
            mfe = 0.0
            mae = 0.0
            pierced = False
            bounced = False
            for h in range(1, max(horizons) + 1):
                j = i + h
                if j >= len(daily_bars):
                    break
                hi = float(daily_bars[j]["high"])
                lo = float(daily_bars[j]["low"])
                c = float(daily_bars[j]["close"])
                if side == "call":
                    # wall above: bounce = reject down; pierce = close above wall
                    mfe = max(mfe, fp - lo)
                    mae = max(mae, hi - fp)
                    if c > wall:
                        pierced = True
                    if h <= 3 and c < wall and lo <= wall <= hi:
                        bounced = True
                else:
                    mfe = max(mfe, hi - fp)
                    mae = max(mae, fp - lo)
                    if c < wall:
                        pierced = True
                    if h <= 3 and c > wall and lo <= wall <= hi:
                        bounced = True
            if pierced:
                outcome = "pierce"
            elif bounced:
                outcome = "bounce"
            row = {
                "date": d,
                "side": side,
                "wall": wall,
                "futures": fp,
                "dist_atr": round(dist, 4),
                "outcome": outcome,
                "mfe_atr": round(mfe / atr, 4),
                "mae_atr": round(mae / atr, 4),
            }
            for h in horizons:
                j = i + h
                if j < len(daily_bars):
                    c = float(daily_bars[j]["close"])
                    # positive = move away from wall favorably for mean-revert thesis
                    if side == "call":
                        row[f"ret_{h}"] = round((fp - c) / fp, 6)  # down after near call wall
                    else:
                        row[f"ret_{h}"] = round((c - fp) / fp, 6)
                else:
                    row[f"ret_{h}"] = None
            events.append(row)

    counts: dict[str, int] = {}
    for e in events:
        counts[e["outcome"]] = counts.get(e["outcome"], 0) + 1
    n = len(events) or 1
    return {
        "ok": True,
        "schema": "cta-gamma-touch-v1",
        "contract": contract.upper(),
        "n_events": len(events),
        "touch_atr": touch_atr,
        "outcome_counts": counts,
        "outcome_probs": {k: round(v / max(len(events), 1), 4) for k, v in counts.items()},
        "events": events,
        "live_trading": False,
        "note": "Sparse when gamma history is short; not a trade signal.",
    }
