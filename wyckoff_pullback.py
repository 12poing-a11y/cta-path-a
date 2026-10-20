# -*- coding: utf-8 -*-
"""
Trend + pullback entry with a rule-based Wyckoff volume-price filter.

Systematic (daily) mapping — not discretionary chart reading:
  1) Trend: EMA20 vs EMA60 + 20/60 return same sign (with optional floors)
  2) Pullback: price retraces toward EMA20 without breaking EMA60 structure
  3) Wyckoff effort/result: pullback volume dries up; resume bar volume returns
  4) Risk: stop beyond pullback extreme; take-profit at reward_rr × stop distance (default 5:1)
"""
from __future__ import annotations

from typing import Any


def ema(hist: list[dict], i: int, n: int) -> float | None:
    if i < n - 1:
        return None
    k = 2 / (n + 1)
    v = hist[i - n + 1]["close"]
    for j in range(i - n + 2, i + 1):
        v = hist[j]["close"] * k + v * (1 - k)
    return v


def sma_volume(hist: list[dict], i: int, n: int = 20) -> float | None:
    if i < n - 1:
        return None
    vals = []
    for j in range(i - n + 1, i + 1):
        v = hist[j].get("volume")
        if v is None or v <= 0:
            return None
        vals.append(float(v))
    return sum(vals) / len(vals) if vals else None


def ret_n(hist: list[dict], i: int, n: int) -> float | None:
    if i < n:
        return None
    a, b = hist[i - n]["close"], hist[i]["close"]
    if a == 0:
        return None
    return (b / a - 1) * 100


def atr14(hist: list[dict], i: int) -> float | None:
    if i < 14:
        return None
    trs = []
    for j in range(i - 13, i + 1):
        h, l, pc = hist[j]["high"], hist[j]["low"], hist[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def _vol(hist: list[dict], j: int) -> float | None:
    v = hist[j].get("volume")
    if v is None or v <= 0:
        return None
    return float(v)


def detect_entry(
    hist: list[dict],
    i: int,
    *,
    min_r20_pct: float = 3.0,
    min_r60_pct: float = 5.0,
    pullback_lookback: int = 8,
    reward_rr: float = 5.0,
) -> dict[str, Any] | None:
    """
    Return entry plan dict or None.
    Fields: direction, entry, stop, target, atr, r20, r60, wyckoff_ok, reason
    """
    if i < max(60, pullback_lookback + 5):
        return None
    e20, e60 = ema(hist, i, 20), ema(hist, i, 60)
    r20, r60 = ret_n(hist, i, 20), ret_n(hist, i, 60)
    a = atr14(hist, i)
    if None in (e20, e60, r20, r60, a) or a <= 0:
        return None
    if abs(r20) < min_r20_pct or abs(r60) < min_r60_pct:
        return None
    # trend alignment
    if r20 > 0 and r60 > 0 and e20 > e60:
        direction = "多"
    elif r20 < 0 and r60 < 0 and e20 < e60:
        direction = "空"
    else:
        return None

    close = hist[i]["close"]
    high = hist[i]["high"]
    low = hist[i]["low"]
    prev = hist[i - 1]
    vma = sma_volume(hist, i, 20)
    vol_i = _vol(hist, i)

    # pullback window excluding today (structure formed before trigger bar)
    w0, w1 = i - pullback_lookback, i - 1
    win = hist[w0 : w1 + 1]
    if len(win) < 3:
        return None

    if direction == "多":
        # structure: still above EMA60; dipped toward EMA20
        swing_low = min(b["low"] for b in win)
        touched = any(b["low"] <= e20 * 1.01 for b in win) or swing_low <= e20 * 1.02
        structure_ok = swing_low > e60 * 0.995 and close > e60
        # Wyckoff: dry-up on pullback days (avg vol of 3 weakest closes near EMA)
        pb_vols = [_vol(hist, j) for j in range(w0, w1 + 1)]
        pb_vols = [v for v in pb_vols if v is not None]
        dry = True
        if vma and pb_vols:
            dry = (sum(pb_vols) / len(pb_vols)) <= vma * 0.9
        # resume: reclaim prior high or close back above EMA20 with volume returning
        reclaim = close > prev["high"] or (close >= e20 and close > prev["close"])
        vol_return = True if (vma is None or vol_i is None) else (vol_i >= vma * 0.85)
        if not (touched and structure_ok and reclaim and dry and vol_return):
            return None
        stop = min(swing_low, low) - 0.05 * a
        if stop >= close:
            stop = close - max(0.5 * a, close * 0.005)
        risk = close - stop
        if risk <= 0:
            return None
        target = close + reward_rr * risk
        return {
            "direction": direction,
            "entry": close,
            "stop": stop,
            "target": target,
            "atr": a,
            "r20": r20,
            "r60": r60,
            "wyckoff_ok": bool(dry and vol_return),
            "vol_filter": vma is not None,
            "reason": "趋势多+回踩量缩+收复",
        }

    # short
    swing_high = max(b["high"] for b in win)
    touched = any(b["high"] >= e20 * 0.99 for b in win) or swing_high >= e20 * 0.98
    structure_ok = swing_high < e60 * 1.005 and close < e60
    pb_vols = [_vol(hist, j) for j in range(w0, w1 + 1)]
    pb_vols = [v for v in pb_vols if v is not None]
    dry = True
    if vma and pb_vols:
        dry = (sum(pb_vols) / len(pb_vols)) <= vma * 0.9
    reclaim = close < prev["low"] or (close <= e20 and close < prev["close"])
    vol_return = True if (vma is None or vol_i is None) else (vol_i >= vma * 0.85)
    if not (touched and structure_ok and reclaim and dry and vol_return):
        return None
    stop = max(swing_high, high) + 0.05 * a
    if stop <= close:
        stop = close + max(0.5 * a, close * 0.005)
    risk = stop - close
    if risk <= 0:
        return None
    target = close - reward_rr * risk
    return {
        "direction": direction,
        "entry": close,
        "stop": stop,
        "target": target,
        "atr": a,
        "r20": r20,
        "r60": r60,
        "wyckoff_ok": bool(dry and vol_return),
        "vol_filter": vma is not None,
        "reason": "趋势空+反弹量缩+失守",
    }


def apply_stop_target(
    direction: str,
    entry: float,
    stop: float,
    target: float,
    bar: dict,
) -> tuple[str | None, float]:
    """
    Intrabar stop/target. Conservative: stop checked before target on same bar.
    Returns (exit_reason, exit_price) or (None, close).
    """
    high, low, close = bar["high"], bar["low"], bar["close"]
    if direction == "多":
        if low <= stop:
            return "stop", stop
        if high >= target:
            return "target", target
        return None, close
    if high >= stop:
        return "stop", stop
    if low <= target:
        return "target", target
    return None, close
