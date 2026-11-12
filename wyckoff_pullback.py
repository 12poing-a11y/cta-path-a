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


def sma_close(hist: list[dict], i: int, n: int) -> float | None:
    if i < n - 1 or n <= 0:
        return None
    vals = []
    for j in range(i - n + 1, i + 1):
        try:
            vals.append(float(hist[j]["close"]))
        except (KeyError, TypeError, ValueError):
            return None
    return sum(vals) / len(vals) if vals else None


def trend_ma60_60m(
    bars_60m: list[dict],
    *,
    asof: str | None = None,
    ma_n: int = 60,
    slope_bars: int = 5,
) -> dict[str, Any] | None:
    """True 60-minute MA60 trend (ChatGPT HTF filter).

    Long: close > MA60 and MA60 rising vs ``slope_bars`` ago.
    Short: close < MA60 and MA60 falling.
    Flat / insufficient history → None.
    """
    if not bars_60m:
        return None
    rows = sorted(
        bars_60m,
        key=lambda b: str(b.get("datetime") or b.get("date") or ""),
    )
    if asof:
        asof_iso = str(asof)[:10]
        rows = [
            b
            for b in rows
            if str(b.get("datetime") or b.get("date") or "")[:10] <= asof_iso
        ]
    if len(rows) < ma_n + slope_bars:
        return None
    i = len(rows) - 1
    ma_now = sma_close(rows, i, ma_n)
    ma_prev = sma_close(rows, i - slope_bars, ma_n)
    try:
        close = float(rows[i]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if ma_now is None or ma_prev is None or close <= 0:
        return None
    rising = ma_now > ma_prev
    falling = ma_now < ma_prev
    if close > ma_now and rising:
        direction = "多"
    elif close < ma_now and falling:
        direction = "空"
    else:
        return None
    return {
        "direction": direction,
        "ma60": float(ma_now),
        "ma60_prev": float(ma_prev),
        "close": close,
        "asof_bar": str(rows[i].get("datetime") or rows[i].get("date") or ""),
        "n_bars": len(rows),
    }


def _trend_direction(
    hist: list[dict],
    i: int,
    *,
    min_r20_pct: float,
    min_r60_pct: float,
) -> tuple[str, float, float, float, float, float] | None:
    """Daily EMA20/60 + r20/r60 same-sign trend. Returns dir, e20, e60, r20, r60, atr."""
    e20, e60 = ema(hist, i, 20), ema(hist, i, 60)
    r20, r60 = ret_n(hist, i, 20), ret_n(hist, i, 60)
    a = atr14(hist, i)
    if None in (e20, e60, r20, r60, a) or a <= 0:
        return None
    if abs(r20) < min_r20_pct or abs(r60) < min_r60_pct:
        return None
    if r20 > 0 and r60 > 0 and e20 > e60:
        return "多", float(e20), float(e60), float(r20), float(r60), float(a)
    if r20 < 0 and r60 < 0 and e20 < e60:
        return "空", float(e20), float(e60), float(r20), float(r60), float(a)
    return None


def detect_entry_abc(
    hist: list[dict],
    i: int,
    *,
    variant: str,
    min_r20_pct: float = 4.0,
    min_r60_pct: float = 6.0,
    pullback_lookback: int = 8,
    reward_rr: float = 2.0,
    stop_atr_mult: float = 0.8,
    htf_direction: str | None = None,
) -> dict[str, Any] | None:
    """Three systematic pullback variants (daily bars).

    A — MA trend pullback: touch EMA20, hold EMA60, reclaim; stop beyond swing.
    B — same entry as A; stop = ATR×stop_atr_mult from entry (formal-style).
    C — A plus liquidity sweep of prior swing + volume dry/return + OI confirm;
        stop beyond sweep extreme.

    When ``htf_direction`` is set (e.g. from ``trend_ma60_60m``), it overrides the
    daily r20/r60 floor gate; daily EMA20/60 still define pullback geometry.
    """
    variant = str(variant or "A").upper().strip()
    if variant not in ("A", "B", "C"):
        raise ValueError(f"variant must be A/B/C, got {variant}")
    if i < max(60, pullback_lookback + 8):
        return None
    a = atr14(hist, i)
    e20, e60 = ema(hist, i, 20), ema(hist, i, 60)
    r20, r60 = ret_n(hist, i, 20), ret_n(hist, i, 60)
    if None in (a, e20, e60) or a <= 0:
        return None
    if htf_direction in ("多", "空"):
        direction = htf_direction
        # Geometry must agree with HTF side.
        if direction == "多" and not (e20 > e60):
            return None
        if direction == "空" and not (e20 < e60):
            return None
        r20 = float(r20 or 0.0)
        r60 = float(r60 or 0.0)
    else:
        trend = _trend_direction(
            hist, i, min_r20_pct=min_r20_pct, min_r60_pct=min_r60_pct
        )
        if trend is None:
            return None
        direction, e20, e60, r20, r60, a = trend
    close = float(hist[i]["close"])
    high = float(hist[i]["high"])
    low = float(hist[i]["low"])
    prev = hist[i - 1]
    w0, w1 = i - pullback_lookback, i - 1
    win = hist[w0 : w1 + 1]
    if len(win) < 3:
        return None
    # prior swing window just before pullback (liquidity pool)
    p0, p1 = w0 - 5, w0 - 1
    if p0 < 1:
        return None
    prior = hist[p0 : p1 + 1]
    if len(prior) < 3:
        return None

    vma = sma_volume(hist, i, 20)
    vol_i = _vol(hist, i)
    pb_vols = [_vol(hist, j) for j in range(w0, w1 + 1)]
    pb_vols = [v for v in pb_vols if v is not None]
    dry = True
    if vma and pb_vols:
        dry = (sum(pb_vols) / len(pb_vols)) <= vma * 0.9
    vol_return = True if (vma is None or vol_i is None) else (vol_i >= vma * 0.85)

    def _oi(j: int) -> float | None:
        v = hist[j].get("open_interest")
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    oi_i, oi_p = _oi(i), _oi(i - 1)
    oi_ok = True if (oi_i is None or oi_p is None) else (oi_i >= oi_p)

    if direction == "多":
        swing_low = min(float(b["low"]) for b in win)
        prior_low = min(float(b["low"]) for b in prior)
        touched = any(float(b["low"]) <= e20 * 1.01 for b in win) or swing_low <= e20 * 1.02
        structure_ok = swing_low > e60 * 0.995 and close > e60
        reclaim = close > float(prev["high"]) or (close >= e20 and close > float(prev["close"]))
        # liquidity sweep: pullback took out prior swing low, then closed back above it
        swept = any(
            float(b["low"]) < prior_low and float(b["close"]) > prior_low for b in win
        ) or (low < prior_low and close > prior_low)
        if not (touched and structure_ok and reclaim):
            return None
        if variant == "C" and not (swept and dry and vol_return and oi_ok):
            return None
        if variant == "B":
            stop = close - stop_atr_mult * a
        else:
            # A/C: stop beyond pullback (and sweep) extreme
            stop = min(swing_low, low) - 0.05 * a
            if stop >= close:
                stop = close - max(0.5 * a, close * 0.005)
        risk = close - stop
        if risk <= 0:
            return None
        target = close + reward_rr * risk
        reason = {
            "A": "均线趋势回调多",
            "B": "趋势回调多+ATR止损",
            "C": "趋势回调多+扫荡+量仓确认",
        }[variant]
        return {
            "direction": direction,
            "entry": close,
            "stop": stop,
            "target": target,
            "atr": a,
            "r20": r20,
            "r60": r60,
            "variant": variant,
            "wyckoff_ok": bool(dry and vol_return),
            "sweep_ok": bool(swept) if variant == "C" else None,
            "oi_ok": bool(oi_ok) if variant == "C" else None,
            "vol_filter": vma is not None,
            "reason": reason,
        }

    swing_high = max(float(b["high"]) for b in win)
    prior_high = max(float(b["high"]) for b in prior)
    touched = any(float(b["high"]) >= e20 * 0.99 for b in win) or swing_high >= e20 * 0.98
    structure_ok = swing_high < e60 * 1.005 and close < e60
    reclaim = close < float(prev["low"]) or (close <= e20 and close < float(prev["close"]))
    swept = any(
        float(b["high"]) > prior_high and float(b["close"]) < prior_high for b in win
    ) or (high > prior_high and close < prior_high)
    if not (touched and structure_ok and reclaim):
        return None
    if variant == "C" and not (swept and dry and vol_return and oi_ok):
        return None
    if variant == "B":
        stop = close + stop_atr_mult * a
    else:
        stop = max(swing_high, high) + 0.05 * a
        if stop <= close:
            stop = close + max(0.5 * a, close * 0.005)
    risk = stop - close
    if risk <= 0:
        return None
    target = close - reward_rr * risk
    reason = {
        "A": "均线趋势回调空",
        "B": "趋势回调空+ATR止损",
        "C": "趋势回调空+扫荡+量仓确认",
    }[variant]
    return {
        "direction": direction,
        "entry": close,
        "stop": stop,
        "target": target,
        "atr": a,
        "r20": r20,
        "r60": r60,
        "variant": variant,
        "wyckoff_ok": bool(dry and vol_return),
        "sweep_ok": bool(swept) if variant == "C" else None,
        "oi_ok": bool(oi_ok) if variant == "C" else None,
        "vol_filter": vma is not None,
        "reason": reason,
    }


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


def minute_bars_aligned_with_entry(
    entry: float,
    minute_bars: list[dict],
    *,
    max_rel_diff: float = 0.05,
) -> bool:
    """True when minute session mid is within ``max_rel_diff`` of entry.

    Continuous-contract stop/target levels must not be compared to month-contract
    minute bars at a different absolute price (false stop/target hits).
    """
    try:
        entry_f = float(entry)
    except (TypeError, ValueError):
        return False
    if entry_f <= 0 or not minute_bars:
        return False
    mids: list[float] = []
    for bar in minute_bars:
        try:
            high = float(bar["high"])
            low = float(bar["low"])
        except (KeyError, TypeError, ValueError):
            continue
        mids.append(0.5 * (high + low))
    if not mids:
        return False
    mids.sort()
    mid = mids[len(mids) // 2]
    return abs(mid - entry_f) / entry_f <= float(max_rel_diff)


def apply_stop_target_intraday(
    direction: str,
    entry: float,
    stop: float,
    target: float,
    minute_bars: list[dict],
) -> tuple[str | None, float | None]:
    """Walk minute bars in time order; first touch wins.

    Within a single bar, stop is still checked before target (same as daily).
    Returns (reason, price) or (None, None) if nothing touched.
    Caller should skip minute bars that fail ``minute_bars_aligned_with_entry``.
    """
    if not minute_bars:
        return None, None
    rows = sorted(
        minute_bars,
        key=lambda b: str(b.get("datetime") or b.get("date") or ""),
    )
    last_close = None
    for bar in rows:
        try:
            high = float(bar["high"])
            low = float(bar["low"])
            close = float(bar["close"])
        except (KeyError, TypeError, ValueError):
            continue
        last_close = close
        reason, px = apply_stop_target(direction, entry, stop, target, bar)
        if reason:
            return reason, float(px)
    return None, last_close
