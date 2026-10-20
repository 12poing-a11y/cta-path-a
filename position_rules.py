# -*- coding: utf-8 -*-
"""Path-A portfolio caps: max N symbols + gross notional ≤ equity × pct."""
from __future__ import annotations

import math
from typing import Any


def compound_equity(live_equity: float, base_equity: float = 200_000, compound: bool = True) -> float:
    """
    Sizing equity: when compound=True, scale with live equity as it grows past base
    (and shrink if underwater). When False, always size on base_equity.
    """
    base = float(base_equity or 0)
    live = float(live_equity or 0)
    if not compound:
        return base if base > 0 else live
    eq = live if live > 0 else base
    return eq if eq > 0 else base


def risk_budget_yuan(equity: float, risk_pct: float = 1.5, l1_mult: float = 1.0) -> float:
    return float(equity) * float(risk_pct) / 100.0 * float(l1_mult)


def _strength(sig: dict) -> float:
    r20 = abs(float(sig.get("r20") or 0))
    r60 = abs(float(sig.get("r60") or 0))
    return r20 + r60


def _notional(lots: int, close: float | None, mult: float) -> float:
    if lots <= 0 or close is None or close <= 0 or mult <= 0:
        return 0.0
    return abs(lots) * float(close) * float(mult)


def apply_portfolio_caps(
    candidates: list[dict[str, Any]],
    *,
    equity: float,
    max_positions: int = 3,
    max_gross_exposure_pct: float = 50.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Keep at most `max_positions` aligned names (by |r20|+|r60|), then scale lots
    so sum(|lots|×close×mult) ≤ equity × max_gross_exposure_pct / 100.

    Each candidate should already have: code, direction, lots, close, mult, r20, r60
    (and optional atr). Returns (selected list with final lots, meta).
    """
    meta: dict[str, Any] = {
        "max_positions": max_positions,
        "max_gross_exposure_pct": max_gross_exposure_pct,
        "candidates_n": len(candidates),
        "scale": 1.0,
        "gross_before": 0.0,
        "gross_after": 0.0,
        "dropped": [],
    }
    if equity <= 0:
        return [], meta

    ranked = sorted(candidates, key=_strength, reverse=True)
    selected = ranked[: max(0, int(max_positions))]
    meta["dropped"] = [c.get("code") for c in ranked[int(max_positions) :]]

    gross = sum(
        _notional(int(c.get("lots") or 0), c.get("close"), float(c.get("mult") or 0))
        for c in selected
    )
    meta["gross_before"] = round(gross, 2)
    cap = equity * float(max_gross_exposure_pct) / 100.0

    if gross > cap and gross > 0:
        scale = cap / gross
        meta["scale"] = round(scale, 4)
        for c in selected:
            lots = int(c.get("lots") or 0)
            c["lots"] = int(math.floor(lots * scale))
        # Drop zero-lot names after scaling; refill from ranked if room (keep ≤ max_positions)
        selected = [c for c in selected if int(c.get("lots") or 0) > 0]
        if len(selected) < max_positions:
            have = {c.get("code") for c in selected}
            for c in ranked:
                if c.get("code") in have:
                    continue
                lots0 = int(c.get("lots") or 0)
                if lots0 <= 0:
                    continue
                trial = dict(c)
                trial["lots"] = int(math.floor(lots0 * scale))
                if trial["lots"] <= 0:
                    continue
                # Accept only if still under cap
                g2 = sum(
                    _notional(int(x.get("lots") or 0), x.get("close"), float(x.get("mult") or 0))
                    for x in selected
                ) + _notional(trial["lots"], trial.get("close"), float(trial.get("mult") or 0))
                if g2 <= cap + 1e-6:
                    selected.append(trial)
                    have.add(trial.get("code"))
                if len(selected) >= max_positions:
                    break

    # Final hard trim if still over (edge: floor rounding)
    while True:
        gross2 = sum(
            _notional(int(c.get("lots") or 0), c.get("close"), float(c.get("mult") or 0))
            for c in selected
        )
        if gross2 <= cap + 1e-6 or not selected:
            meta["gross_after"] = round(gross2, 2)
            break
        # Drop weakest
        selected.sort(key=_strength)
        dropped = selected.pop(0)
        meta["dropped"].append(dropped.get("code"))

    meta["selected"] = [c.get("code") for c in selected]
    meta["gross_pct"] = round(meta["gross_after"] / equity * 100, 2) if equity else 0.0
    return selected, meta
