# -*- coding: utf-8 -*-
"""Vanilla Black-76 Greeks for Vol-V1.4 (shadow only)."""
from __future__ import annotations

from typing import Any

from research.options.pricing.black76 import (
    black76_delta,
    black76_gamma,
    black76_price,
    black76_theta,
    black76_vega,
)


def vanilla_greeks(
    *,
    futures: float,
    strike: float,
    years: float,
    rate: float,
    iv: float,
    side: str,
) -> dict[str, Any]:
    """Return price + Δ/Γ/ν/Θ. Raises on invalid inputs (caller fail-closed)."""
    side_u = str(side).upper()
    price = black76_price(futures, strike, years, rate, iv, side_u)
    delta = black76_delta(futures, strike, years, rate, iv, side_u)
    gamma = black76_gamma(futures, strike, years, rate, iv)
    vega = black76_vega(futures, strike, years, rate, iv)
    theta = black76_theta(futures, strike, years, rate, iv, side_u)
    return {
        "price": round(float(price), 8),
        "delta": round(float(delta), 8),
        "gamma": round(float(gamma), 10),
        "vega": round(float(vega), 8),
        "theta": round(float(theta), 8),
        "theta_per_day": round(float(theta) / 365.0, 8),
        "iv": round(float(iv), 8),
        "side": side_u,
        "strike": float(strike),
        "futures": float(futures),
        "years": float(years),
    }
