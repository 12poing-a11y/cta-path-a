# -*- coding: utf-8 -*-
"""Vertical credit spreads for research (settle_discount or bid/ask)."""
from __future__ import annotations

from typing import Any, Literal

from research.options.specs import get_spec, slip_discount_points

SpreadKind = Literal["put_credit", "call_credit"]
PricingMode = Literal["settle_discount", "bid_ask"]


def _leg_px(leg: dict[str, Any], *, role: str, mode: PricingMode) -> float | None:
    """role=short → sell (bid preferred); role=long → buy (ask preferred)."""
    if mode == "bid_ask":
        if role == "short":
            px = leg.get("bid")
        else:
            px = leg.get("ask")
        if px is not None and float(px) > 0:
            return float(px)
        # fall through to settle
    settle = leg.get("settle")
    if settle is None:
        settle = leg.get("close")
    if settle is None or float(settle) < 0:
        return None
    return float(settle)


def _nearest_leg(
    legs: list[dict[str, Any]],
    *,
    side: str,
    target: float,
    prefer: Literal["lte", "gte", "abs"] = "abs",
) -> dict[str, Any] | None:
    cand = [lg for lg in legs if lg.get("side") == side and lg.get("strike") is not None]
    if not cand:
        return None
    if prefer == "lte":
        pool = [lg for lg in cand if float(lg["strike"]) <= target]
        if not pool:
            pool = cand
        return min(pool, key=lambda lg: (abs(float(lg["strike"]) - target), -float(lg["strike"])))
    if prefer == "gte":
        pool = [lg for lg in cand if float(lg["strike"]) >= target]
        if not pool:
            pool = cand
        return min(pool, key=lambda lg: (abs(float(lg["strike"]) - target), float(lg["strike"])))
    return min(cand, key=lambda lg: abs(float(lg["strike"]) - target))


def _find_by_strike(legs: list[dict[str, Any]], side: str, strike: float, tol: float = 1e-6):
    for lg in legs:
        if lg.get("side") == side and abs(float(lg["strike"]) - strike) <= tol:
            return lg
    return None


def select_credit_vertical(
    snap: dict[str, Any],
    *,
    kind: SpreadKind = "put_credit",
    width_points: float = 200.0,
    slip_ticks: float = 2.0,
    prefer_bid_ask: bool = True,
) -> dict[str, Any] | None:
    """Pick short/long legs near ATM. Returns None if legs/prices missing."""
    F = snap.get("underlying_settle")
    legs = snap.get("legs") or []
    if F is None or float(F) <= 0 or not legs:
        return None
    F = float(F)
    code = str(snap.get("code") or "").upper()
    try:
        spec = get_spec(code, include_observe=True)
        opt_tick = float(spec.option_tick)
        mult = float(spec.multiplier)
    except KeyError:
        opt_tick = 1.0
        mult = float(snap.get("multiplier") or 1.0)

    q = snap.get("quality") or {}
    has_ba = int(q.get("n_with_bid_ask") or 0) > 0
    mode: PricingMode = "bid_ask" if (prefer_bid_ask and has_ba) else "settle_discount"

    if kind == "put_credit":
        short = _nearest_leg(legs, side="P", target=F, prefer="lte")
        if short is None:
            return None
        ks = float(short["strike"])
        long = _find_by_strike(legs, "P", ks - float(width_points))
        if long is None:
            # nearest put at least width below
            below = [
                lg
                for lg in legs
                if lg.get("side") == "P" and float(lg["strike"]) <= ks - float(width_points) * 0.5
            ]
            if not below:
                return None
            long = min(below, key=lambda lg: abs(float(lg["strike"]) - (ks - float(width_points))))
    else:
        short = _nearest_leg(legs, side="C", target=F, prefer="gte")
        if short is None:
            return None
        ks = float(short["strike"])
        long = _find_by_strike(legs, "C", ks + float(width_points))
        if long is None:
            above = [
                lg
                for lg in legs
                if lg.get("side") == "C" and float(lg["strike"]) >= ks + float(width_points) * 0.5
            ]
            if not above:
                return None
            long = min(above, key=lambda lg: abs(float(lg["strike"]) - (ks + float(width_points))))

    kl = float(long["strike"])
    width = abs(ks - kl)
    if width <= 0:
        return None

    px_s = _leg_px(short, role="short", mode=mode)
    px_l = _leg_px(long, role="long", mode=mode)
    if px_s is None or px_l is None:
        return None

    raw_credit = px_s - px_l
    slip = 0.0
    if mode == "settle_discount":
        slip = slip_discount_points(slip_ticks=slip_ticks, option_tick=opt_tick)
    credit = raw_credit - slip
    if credit <= 0:
        return None

    return {
        "strategy_id": "credit_vertical",
        "kind": kind,
        "asof": snap.get("asof"),
        "code": code,
        "underlying_settle": F,
        "short": {"symbol": short.get("symbol"), "side": short.get("side"), "strike": ks, "px": px_s},
        "long": {"symbol": long.get("symbol"), "side": long.get("side"), "strike": kl, "px": px_l},
        "width_points": width,
        "raw_credit_points": raw_credit,
        "slip_points": slip,
        "credit_points": credit,
        "pricing_mode": mode,
        "multiplier": mult,
        "quality_status": q.get("status"),
        "legs": [short, long],
    }


def expiry_pnl_points(
    *,
    kind: SpreadKind,
    short_strike: float,
    long_strike: float,
    credit_points: float,
    futures_settle: float,
) -> float:
    """PnL in price points at futures expiry settlement."""
    F = float(futures_settle)
    ks, kl = float(short_strike), float(long_strike)
    if kind == "put_credit":
        exit_val = max(0.0, ks - F) - max(0.0, kl - F)
    else:
        exit_val = max(0.0, F - ks) - max(0.0, F - kl)
    return float(credit_points) - exit_val


def mtm_close_debit(
    snap: dict[str, Any],
    trade: dict[str, Any],
    *,
    prefer_bid_ask: bool = True,
) -> float | None:
    """Debit to close (buy short, sell long) in points on a later snapshot."""
    legs = snap.get("legs") or []
    ks = float(trade["short"]["strike"])
    kl = float(trade["long"]["strike"])
    side = "P" if trade["kind"] == "put_credit" else "C"
    short = _find_by_strike(legs, side, ks)
    long = _find_by_strike(legs, side, kl)
    if short is None or long is None:
        return None
    q = snap.get("quality") or {}
    has_ba = int(q.get("n_with_bid_ask") or 0) > 0
    mode: PricingMode = "bid_ask" if (prefer_bid_ask and has_ba) else "settle_discount"
    # close: buy short (ask), sell long (bid)
    if mode == "bid_ask":
        buy = short.get("ask") if short.get("ask") is not None else short.get("settle")
        sell = long.get("bid") if long.get("bid") is not None else long.get("settle")
    else:
        buy = short.get("settle") if short.get("settle") is not None else short.get("close")
        sell = long.get("settle") if long.get("settle") is not None else long.get("close")
    if buy is None or sell is None:
        return None
    return float(buy) - float(sell)
