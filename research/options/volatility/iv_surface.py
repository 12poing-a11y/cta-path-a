# -*- coding: utf-8 -*-
"""Chain IV grid with quality marks (Vol-V1.4 · shadow only).

Never fills IV=0 on solver failure — marks invalid instead.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from research.options.pricing.black76 import black76_delta, implied_vol

SCHEMA = "cta-iv-surface-v1"
DEFAULT_RATE = 0.02


def _parse_ymd(raw: Any) -> date | None:
    s = str(raw or "").strip()[:10]
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def years_to_expiry(asof: str | date, expiry: str | date | None) -> float | None:
    a = asof if isinstance(asof, date) else _parse_ymd(asof)
    e = expiry if isinstance(expiry, date) else _parse_ymd(expiry)
    if a is None or e is None:
        return None
    days = (e - a).days
    if days <= 0:
        return None
    return days / 365.0


def leg_premium(leg: dict[str, Any]) -> tuple[float | None, str | None]:
    """Premium priority: mid(bid,ask) → settle → close. Reject inverted book."""
    bid = leg.get("bid")
    ask = leg.get("ask")
    try:
        bid_f = float(bid) if bid is not None else None
        ask_f = float(ask) if ask is not None else None
    except (TypeError, ValueError):
        bid_f, ask_f = None, None
    if bid_f is not None and ask_f is not None:
        if bid_f > ask_f:
            return None, "bid_gt_ask"
        if bid_f > 0 and ask_f > 0:
            return 0.5 * (bid_f + ask_f), "mid"
    for key, tag in (("settle", "settle"), ("close", "close")):
        try:
            px = float(leg[key]) if leg.get(key) is not None else None
        except (TypeError, ValueError, KeyError):
            px = None
        if px is not None and px > 0 and math.isfinite(px):
            return px, tag
    return None, "no_premium"


def build_iv_surface(
    snap: dict[str, Any],
    *,
    rate: float = DEFAULT_RATE,
) -> dict[str, Any]:
    """Build per-leg IV points from a chain snapshot. Fail-closed on bad legs."""
    code = str(snap.get("code") or "").upper()
    asof = str(snap.get("asof") or "")[:10]
    F = snap.get("underlying_settle")
    try:
        F_f = float(F) if F is not None else None
    except (TypeError, ValueError):
        F_f = None
    years = years_to_expiry(asof, snap.get("expiry"))
    q_snap = (snap.get("quality") or {}).get("status") or "UNKNOWN"
    points: list[dict[str, Any]] = []
    n_ok = n_skip = n_fail = 0
    warnings: list[str] = []

    if F_f is None or F_f <= 0:
        return {
            "schema": SCHEMA,
            "ok": False,
            "code": code,
            "asof": asof,
            "error": "missing_futures",
            "points": [],
            "live_trading": False,
            "promote_path_a": False,
        }
    if years is None:
        return {
            "schema": SCHEMA,
            "ok": False,
            "code": code,
            "asof": asof,
            "error": "bad_or_expired_tenor",
            "points": [],
            "live_trading": False,
            "promote_path_a": False,
        }

    n_ba = int((snap.get("quality") or {}).get("n_with_bid_ask") or 0)
    if n_ba <= 0 and q_snap != "OK":
        warnings.append("no_bid_ask_or_quality_warn")

    for leg in snap.get("legs") or []:
        if not isinstance(leg, dict):
            n_skip += 1
            continue
        side = str(leg.get("side") or "").upper()
        if side not in {"C", "P"}:
            n_skip += 1
            continue
        try:
            K = float(leg.get("strike"))
        except (TypeError, ValueError):
            n_skip += 1
            continue
        if K <= 0:
            n_skip += 1
            continue
        prem, prem_src = leg_premium(leg)
        if prem is None:
            n_skip += 1
            points.append(
                {
                    "symbol": leg.get("symbol"),
                    "side": side,
                    "strike": K,
                    "iv": None,
                    "status": "SKIP",
                    "reason": prem_src or "no_premium",
                    "premium": None,
                    "premium_source": prem_src,
                }
            )
            continue
        try:
            iv = implied_vol(prem, F_f, K, years, rate, side)
            if not math.isfinite(iv) or iv <= 0:
                raise ValueError("non_positive_iv")
            delta = black76_delta(F_f, K, years, rate, iv, side)
            points.append(
                {
                    "symbol": leg.get("symbol"),
                    "side": side,
                    "strike": K,
                    "iv": round(float(iv), 8),
                    "delta": round(float(delta), 8),
                    "log_moneyness": round(math.log(K / F_f), 8),
                    "premium": round(float(prem), 6),
                    "premium_source": prem_src,
                    "status": "OK",
                    "reason": None,
                    "bid": leg.get("bid"),
                    "ask": leg.get("ask"),
                }
            )
            n_ok += 1
        except Exception as exc:  # noqa: BLE001
            n_fail += 1
            points.append(
                {
                    "symbol": leg.get("symbol"),
                    "side": side,
                    "strike": K,
                    "iv": None,  # never zero-fill
                    "status": "FAIL",
                    "reason": str(exc)[:120],
                    "premium": round(float(prem), 6),
                    "premium_source": prem_src,
                }
            )

    quality = "OK" if n_ok > 0 and n_fail == 0 else ("WARN" if n_ok > 0 else "REJECT")
    if n_ba <= 0:
        quality = "WARN" if n_ok > 0 else quality
        if "thin_or_no_bid_ask" not in warnings:
            warnings.append("thin_or_no_bid_ask")

    return {
        "schema": SCHEMA,
        "ok": n_ok > 0,
        "code": code,
        "asof": asof,
        "futures": F_f,
        "years": round(years, 8),
        "rate": rate,
        "expiry": snap.get("expiry"),
        "futures_contract": snap.get("futures_contract"),
        "quality": quality,
        "warnings": warnings,
        "n_ok": n_ok,
        "n_skip": n_skip,
        "n_fail": n_fail,
        "points": points,
        "live_trading": False,
        "promote_path_a": False,
    }


def lookup_iv_by_moneyness(
    points: list[dict[str, Any]],
    *,
    side: str,
    log_moneyness: float,
) -> float | None:
    """Linear interpolate IV on log-moneyness for OK points of one side."""
    side_u = str(side).upper()
    rows = [
        (float(p["log_moneyness"]), float(p["iv"]))
        for p in points
        if p.get("status") == "OK"
        and p.get("side") == side_u
        and p.get("iv") is not None
        and p.get("log_moneyness") is not None
    ]
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    if log_moneyness <= rows[0][0]:
        return rows[0][1]
    if log_moneyness >= rows[-1][0]:
        return rows[-1][1]
    for i in range(1, len(rows)):
        x0, y0 = rows[i - 1]
        x1, y1 = rows[i]
        if x0 <= log_moneyness <= x1:
            if abs(x1 - x0) < 1e-15:
                return y0
            w = (log_moneyness - x0) / (x1 - x0)
            return y0 + w * (y1 - y0)
    return None


def lookup_iv_by_strike(
    points: list[dict[str, Any]],
    *,
    side: str,
    strike: float,
) -> float | None:
    side_u = str(side).upper()
    exact = [
        float(p["iv"])
        for p in points
        if p.get("status") == "OK"
        and p.get("side") == side_u
        and p.get("iv") is not None
        and abs(float(p["strike"]) - float(strike)) < 1e-9
    ]
    if exact:
        return exact[0]
    # nearest strike
    cands = [
        (abs(float(p["strike"]) - float(strike)), float(p["iv"]))
        for p in points
        if p.get("status") == "OK" and p.get("side") == side_u and p.get("iv") is not None
    ]
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    return cands[0][1]
