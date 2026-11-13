# -*- coding: utf-8 -*-
"""Split Data Valid Mask vs Tradability Mask; never conflate the two.

Example: limit-locked day can be VALID_ONLY — OHLC usable for research,
but opens/closes that require trading through the lock are blocked.
"""
from __future__ import annotations

import math
from typing import Any

from research_quality import atr_close_ok, parse_ymd, validate_bar_date

# Status vocabulary (upgrade plan P0)
DATA_STATUS = ("PASS", "VALID_ONLY", "DEGRADED", "REJECT", "STALE")


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def data_valid_mask(
    bar: dict[str, Any],
    *,
    asof: str | None = None,
    max_atr_ratio: float = 0.25,
) -> tuple[bool, list[str]]:
    """Whether the bar may be used for factor / structure calculation."""
    reasons: list[str] = []
    o = _f(bar.get("open"))
    h = _f(bar.get("high"))
    l = _f(bar.get("low"))
    c = _f(bar.get("close"))
    if None in (h, l, c):
        # Allow close-only rows used by some signal gates; mark incomplete.
        if c is None:
            reasons.append("missing_close")
        else:
            reasons.append("incomplete_ohlc")
    else:
        if h < l:
            reasons.append("high_lt_low")
        if c < l or c > h:
            reasons.append("close_outside_range")
        if o is not None and (o < l or o > h):
            reasons.append("open_outside_range")
        if c <= 0:
            reasons.append("non_positive_close")

    atr = _f(bar.get("atr"))
    if c is not None and atr is not None and not atr_close_ok(c, atr, max_ratio=max_atr_ratio):
        reasons.append("atr_vs_close")

    bar_date = bar.get("bar_date") or bar.get("date")
    if bar_date:
        ok, reason = validate_bar_date(str(bar_date), asof=asof)
        if not ok:
            reasons.append(reason)

    vol = bar.get("volume")
    if vol is not None:
        try:
            if float(vol) < 0:
                reasons.append("negative_volume")
        except (TypeError, ValueError):
            reasons.append("invalid_volume")

    # Hard rejects only (incomplete OHLC alone → degraded path in classify)
    hard = {
        "missing_close",
        "high_lt_low",
        "close_outside_range",
        "open_outside_range",
        "non_positive_close",
        "atr_vs_close",
        "bar_date_unparsed",
        "bar_date_weekend",
        "bar_date_future",
        "negative_volume",
        "invalid_volume",
    }
    invalid = bool(hard.intersection(reasons))
    return (not invalid), reasons


def _limit_locked(
    bar: dict[str, Any],
    *,
    prev_close: float | None = None,
    limit_pct: float | None = None,
) -> tuple[bool, str | None]:
    """Heuristic lock detection when exchange limit flags are absent."""
    flag = bar.get("limit_locked") or bar.get("limit_status")
    if flag in ("up", "down", "locked", True, "Y", "y", 1):
        return True, "limit_flag"
    if str(flag).lower() in ("limit_up", "limit_down", "涨停", "跌停"):
        return True, "limit_flag"

    h = _f(bar.get("high"))
    l = _f(bar.get("low"))
    c = _f(bar.get("close"))
    o = _f(bar.get("open"))
    if None in (h, l, c):
        return False, None
    # Flat bar with no range
    if h == l == c and (o is None or o == c):
        if prev_close and prev_close > 0 and limit_pct and limit_pct > 0:
            move = abs(c - prev_close) / prev_close
            if move >= float(limit_pct) * 0.95:
                return True, "flat_near_limit"
        # Without prev/limit context, flat day alone is liquidity suspicion not hard lock
        return False, None
    return False, None


def tradability_mask(
    bar: dict[str, Any],
    *,
    side: str | None = None,
    prev_close: float | None = None,
    limit_pct: float | None = None,
    require_next_open: bool = False,
    next_open: float | None = None,
    min_volume: float = 0.0,
) -> tuple[bool, list[str]]:
    """Whether a realistic fill could occur at this decision/execution point."""
    reasons: list[str] = []
    vol = _f(bar.get("volume"))
    if vol is not None and vol <= float(min_volume):
        reasons.append("no_volume")

    locked, how = _limit_locked(bar, prev_close=prev_close, limit_pct=limit_pct)
    if locked:
        reasons.append(how or "limit_locked")
        # Directional nuance when side known
        status = str(bar.get("limit_status") or bar.get("limit_locked") or "").lower()
        if side in ("多", "long", "buy") and status in ("down", "跌停", "limit_down"):
            reasons.append("cannot_buy_limit_down")
        if side in ("空", "short", "sell") and status in ("up", "涨停", "limit_up"):
            reasons.append("cannot_sell_limit_up")

    if bar.get("delivery_restricted") or bar.get("near_delivery"):
        reasons.append("delivery_restricted")
    if bar.get("roll_blocked") or bar.get("no_new_position"):
        reasons.append("roll_or_position_blocked")
    if bar.get("listed") is False:
        reasons.append("not_listed")

    if require_next_open:
        no = _f(next_open if next_open is not None else bar.get("next_open"))
        if no is None or no <= 0:
            reasons.append("missing_next_open")

    # Continuous series must not pretend to be executable contract fills
    basis = str(bar.get("price_basis") or "contract").strip().lower()
    if basis == "continuous" and bar.get("allow_continuous_fill") is not True:
        reasons.append("continuous_not_executable")

    return (len(reasons) == 0), reasons


def quality_score(
    *,
    data_valid: bool,
    tradable: bool,
    reasons: list[str],
    degraded_keys: frozenset[str] | None = None,
) -> float:
    """Credibility score in [0, 1] — not a trading signal."""
    degraded_keys = degraded_keys or frozenset({"incomplete_ohlc", "optional_missing"})
    if not data_valid and any(
        r not in degraded_keys for r in reasons
    ):
        # hard reject path
        if any(r.startswith("bar_date_") or r in {"missing_close", "atr_vs_close"} for r in reasons):
            return 0.0
    score = 1.0
    if not data_valid:
        score -= 0.45
    if not tradable:
        score -= 0.25
    soft = [r for r in reasons if r in degraded_keys or r == "incomplete_ohlc"]
    score -= 0.08 * len(soft)
    score -= 0.05 * max(0, len(reasons) - len(soft))
    return max(0.0, min(1.0, round(score, 4)))


def classify_bar(
    bar: dict[str, Any],
    *,
    asof: str | None = None,
    side: str | None = None,
    prev_close: float | None = None,
    limit_pct: float | None = None,
    require_next_open: bool = False,
    next_open: float | None = None,
    stale: bool = False,
) -> dict[str, Any]:
    """Return status + masks. REJECT/STALE never enter formal fills."""
    from research.data_quality.schema import bar_quality_record

    valid, v_reasons = data_valid_mask(bar, asof=asof)
    tradable, t_reasons = tradability_mask(
        bar,
        side=side,
        prev_close=prev_close,
        limit_pct=limit_pct,
        require_next_open=require_next_open,
        next_open=next_open,
    )
    reasons = list(dict.fromkeys([*v_reasons, *t_reasons]))
    if stale and "stale" not in reasons:
        reasons.append("stale")

    if stale:
        status = "STALE"
    elif "bar_date_future" in reasons or not valid:
        status = "REJECT"
    elif "incomplete_ohlc" in reasons:
        status = "DEGRADED"
    elif not tradable:
        status = "VALID_ONLY"
    else:
        status = "PASS"

    qs = quality_score(data_valid=valid, tradable=tradable, reasons=reasons)
    code = str(bar.get("code") or bar.get("symbol") or "?")
    bar_date = bar.get("bar_date") or bar.get("date")
    if hasattr(bar_date, "isoformat"):
        bar_date = bar_date.isoformat()
    elif bar_date is not None:
        bar_date = str(bar_date)
        d = parse_ymd(bar_date)
        if d is not None:
            bar_date = d.isoformat()

    data_ok = status in ("PASS", "VALID_ONLY", "DEGRADED")
    return bar_quality_record(
        code=code,
        bar_date=bar_date,
        status=status,
        data_valid=data_ok,
        tradable=(status == "PASS"),
        reasons=reasons,
        quality_score=qs,
        price_basis=str(bar.get("price_basis") or "contract"),
    )
