# -*- coding: utf-8 -*-
"""Synthetic protective option overlay for Path-A paper observe.

No real option chain: premium = premium_atr_mult × ATR × multiplier × lots
(intentionally large when premium_atr_mult ≥ 1.5–2). Strike at entry ± strike_atr_mult × ATR.
Long futures → buy put; short futures → buy call. Payoff settled at futures exit.
"""
from __future__ import annotations

from typing import Any


def hedge_enabled(cfg: dict[str, Any] | None) -> bool:
    oh = (cfg or {}).get("option_hedge") or {}
    return bool(oh.get("enabled"))


def hedge_params(cfg: dict[str, Any] | None) -> dict[str, float]:
    oh = (cfg or {}).get("option_hedge") or {}
    return {
        "premium_atr_mult": float(oh.get("premium_atr_mult") or 2.0),
        "strike_atr_mult": float(oh.get("strike_atr_mult") or 1.0),
    }


def option_premium(
    *,
    lots: int,
    atr: float,
    mult: float,
    premium_atr_mult: float,
) -> float:
    if lots <= 0 or atr <= 0 or mult <= 0 or premium_atr_mult <= 0:
        return 0.0
    return abs(lots) * float(atr) * float(mult) * float(premium_atr_mult)


def option_strike(
    direction: str,
    entry: float,
    atr: float,
    strike_atr_mult: float,
) -> float:
    dist = float(strike_atr_mult) * float(atr)
    if direction == "多":
        return float(entry) - dist
    return float(entry) + dist


def option_payoff(
    direction: str,
    *,
    lots: int,
    strike: float,
    exit_px: float,
    mult: float,
) -> float:
    """Protective put (long) / call (short) intrinsic at exit."""
    if lots <= 0 or mult <= 0:
        return 0.0
    if direction == "多":
        intrinsic = max(0.0, float(strike) - float(exit_px))
    else:
        intrinsic = max(0.0, float(exit_px) - float(strike))
    return abs(lots) * intrinsic * float(mult)


def attach_hedge_to_position(
    pos: dict[str, Any],
    *,
    atr: float,
    mult: float,
    premium_atr_mult: float,
    strike_atr_mult: float,
) -> dict[str, Any]:
    lots = int(pos.get("lots") or 0)
    direction = str(pos.get("direction") or "多")
    entry = float(pos.get("entry") or 0)
    premium = option_premium(
        lots=lots, atr=atr, mult=mult, premium_atr_mult=premium_atr_mult
    )
    strike = option_strike(direction, entry, atr, strike_atr_mult)
    out = dict(pos)
    out["opt_premium"] = round(premium, 2)
    out["opt_strike"] = round(strike, 4)
    out["opt_atr"] = round(float(atr), 4)
    out["opt_premium_atr_mult"] = float(premium_atr_mult)
    out["opt_strike_atr_mult"] = float(strike_atr_mult)
    return out
