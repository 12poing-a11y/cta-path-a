# -*- coding: utf-8 -*-
"""Shadow Delta / Gamma under Sticky Strike vs Sticky Delta (monitor only).

Not a unique objective Delta — numbers depend on bump size and surface path.
Do not use as auto-trade triggers.
"""
from __future__ import annotations

import math
from typing import Any, Literal

from research.options.pricing.black76 import black76_price
from research.options.volatility.iv_surface import lookup_iv_by_moneyness, lookup_iv_by_strike

Mode = Literal["sticky_strike", "sticky_delta"]


def _bump_frac(futures: float, d_frac: float = 0.01) -> float:
    """Relative futures bump; keeps units consistent across underlyings."""
    return max(float(futures) * float(d_frac), 1e-8)


def shadow_greeks_for_point(
    *,
    futures: float,
    strike: float,
    years: float,
    rate: float,
    side: str,
    iv: float,
    surface_points: list[dict[str, Any]],
    d_frac: float = 0.01,
) -> dict[str, Any]:
    """Compute vanilla + sticky-strike / sticky-delta shadow Δ/Γ for one strike."""
    side_u = str(side).upper()
    dF = _bump_frac(futures, d_frac)
    F_up = futures + dF
    F_dn = max(futures - dF, 1e-8)

    # Sticky Strike: same K keeps same IV
    iv_ss = lookup_iv_by_strike(surface_points, side=side_u, strike=strike)
    if iv_ss is None:
        iv_ss = iv
    p_ss_up = black76_price(F_up, strike, years, rate, iv_ss, side_u)
    p_ss_dn = black76_price(F_dn, strike, years, rate, iv_ss, side_u)
    # second bump for gamma
    F_up2 = futures + 2.0 * dF
    F_dn2 = max(futures - 2.0 * dF, 1e-8)
    p_ss_up2 = black76_price(F_up2, strike, years, rate, iv_ss, side_u)
    p_ss_dn2 = black76_price(F_dn2, strike, years, rate, iv_ss, side_u)
    delta_ss = (p_ss_up - p_ss_dn) / (F_up - F_dn)
    # central second difference using ±dF and ±2dF is noisy; use ±dF three-point
    p0 = black76_price(futures, strike, years, rate, iv_ss, side_u)
    gamma_ss = (p_ss_up - 2.0 * p0 + p_ss_dn) / (dF * dF)
    gamma_ss_up = (p_ss_up2 - 2.0 * p_ss_up + p0) / (dF * dF)
    gamma_ss_dn = (p0 - 2.0 * p_ss_dn + p_ss_dn2) / (dF * dF)

    # Sticky Delta: IV follows log-moneyness on original surface
    def _iv_sd(F: float) -> float:
        lm = math.log(strike / F)
        iv_l = lookup_iv_by_moneyness(surface_points, side=side_u, log_moneyness=lm)
        return float(iv_l) if iv_l is not None else float(iv)

    iv_up = _iv_sd(F_up)
    iv_dn = _iv_sd(F_dn)
    iv_0 = _iv_sd(futures)
    iv_up2 = _iv_sd(F_up2)
    iv_dn2 = _iv_sd(F_dn2)
    p_sd_up = black76_price(F_up, strike, years, rate, iv_up, side_u)
    p_sd_dn = black76_price(F_dn, strike, years, rate, iv_dn, side_u)
    p_sd_0 = black76_price(futures, strike, years, rate, iv_0, side_u)
    p_sd_up2 = black76_price(F_up2, strike, years, rate, iv_up2, side_u)
    p_sd_dn2 = black76_price(F_dn2, strike, years, rate, iv_dn2, side_u)
    delta_sd = (p_sd_up - p_sd_dn) / (F_up - F_dn)
    gamma_sd = (p_sd_up - 2.0 * p_sd_0 + p_sd_dn) / (dF * dF)
    gamma_sd_up = (p_sd_up2 - 2.0 * p_sd_up + p_sd_0) / (dF * dF)
    gamma_sd_dn = (p_sd_0 - 2.0 * p_sd_dn + p_sd_dn2) / (dF * dF)

    return {
        "d_frac": d_frac,
        "dF": round(dF, 8),
        "sticky_strike": {
            "delta": round(delta_ss, 8),
            "gamma": round(gamma_ss, 10),
            "gamma_up": round(gamma_ss_up, 10),
            "gamma_dn": round(gamma_ss_dn, 10),
            "iv_used": round(float(iv_ss), 8),
        },
        "sticky_delta": {
            "delta": round(delta_sd, 8),
            "gamma": round(gamma_sd, 10),
            "gamma_up": round(gamma_sd_up, 10),
            "gamma_dn": round(gamma_sd_dn, 10),
            "iv_at_F": round(float(iv_0), 8),
            "iv_up": round(float(iv_up), 8),
            "iv_dn": round(float(iv_dn), 8),
        },
        "note": "monitor_only_not_trade_signal",
    }
