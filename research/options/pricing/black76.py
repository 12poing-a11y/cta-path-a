# -*- coding: utf-8 -*-
"""Black-76 futures-option pricing (research; not Path-A formal).

Formulas follow the discounted Black model on the futures forward:
  d1 = [ln(F/K) + 0.5 σ² T] / (σ √T)
  d2 = d1 − σ √T
  Call = e^{−rT} [F N(d1) − K N(d2)]
  Put  = e^{−rT} [K N(−d2) − F N(−d1)]
  Gamma = e^{−rT} n(d1) / (F σ √T)   (call = put)
"""
from __future__ import annotations

import math
from typing import Literal

Side = Literal["C", "P", "call", "put"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _side(side: Side) -> str:
    s = str(side).strip().upper()
    if s in {"C", "CALL"}:
        return "C"
    if s in {"P", "PUT"}:
        return "P"
    raise ValueError("side 须为 C/P 或 call/put")


def _validate_inputs(futures: float, strike: float, years: float, iv: float) -> None:
    if futures <= 0 or strike <= 0 or years <= 0 or iv <= 0:
        raise ValueError("F、K、T、IV 必须大于 0")


def _d1_d2(
    futures: float, strike: float, years: float, iv: float
) -> tuple[float, float]:
    vol_t = iv * math.sqrt(years)
    d1 = (math.log(futures / strike) + 0.5 * iv * iv * years) / vol_t
    d2 = d1 - vol_t
    return d1, d2


def black76_price(
    futures: float,
    strike: float,
    years: float,
    rate: float,
    iv: float,
    side: Side,
) -> float:
    """Undiscounted point premium (yuan per underlying unit), one lot notional later."""
    _validate_inputs(futures, strike, years, iv)
    d1, d2 = _d1_d2(futures, strike, years, iv)
    df = math.exp(-rate * years)
    if _side(side) == "C":
        return df * (futures * _norm_cdf(d1) - strike * _norm_cdf(d2))
    return df * (strike * _norm_cdf(-d2) - futures * _norm_cdf(-d1))


def black76_delta(
    futures: float,
    strike: float,
    years: float,
    rate: float,
    iv: float,
    side: Side,
) -> float:
    _validate_inputs(futures, strike, years, iv)
    d1, _ = _d1_d2(futures, strike, years, iv)
    df = math.exp(-rate * years)
    if _side(side) == "C":
        return df * _norm_cdf(d1)
    return df * (_norm_cdf(d1) - 1.0)


def black76_gamma(
    futures: float,
    strike: float,
    years: float,
    rate: float,
    iv: float,
) -> float:
    """Per-unit futures gamma (same for call and put)."""
    _validate_inputs(futures, strike, years, iv)
    d1, _ = _d1_d2(futures, strike, years, iv)
    vol_t = iv * math.sqrt(years)
    return math.exp(-rate * years) * _norm_pdf(d1) / (futures * vol_t)


def black76_vega(
    futures: float,
    strike: float,
    years: float,
    rate: float,
    iv: float,
) -> float:
    """Price sensitivity to σ (per 1.0 absolute vol, not per 1%)."""
    _validate_inputs(futures, strike, years, iv)
    d1, _ = _d1_d2(futures, strike, years, iv)
    return math.exp(-rate * years) * futures * _norm_pdf(d1) * math.sqrt(years)


def black76_theta(
    futures: float,
    strike: float,
    years: float,
    rate: float,
    iv: float,
    side: Side,
) -> float:
    """Calendar theta dV/dT (per year); divide by 365 for per-day approx."""
    _validate_inputs(futures, strike, years, iv)
    d1, d2 = _d1_d2(futures, strike, years, iv)
    df = math.exp(-rate * years)
    pdf = _norm_pdf(d1)
    vol_term = -df * futures * pdf * iv / (2.0 * math.sqrt(years))
    if _side(side) == "C":
        return vol_term + rate * df * (futures * _norm_cdf(d1) - strike * _norm_cdf(d2))
    return vol_term - rate * df * (strike * _norm_cdf(-d2) - futures * _norm_cdf(-d1))


def implied_vol(
    premium: float,
    futures: float,
    strike: float,
    years: float,
    rate: float,
    side: Side,
    *,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-8,
    max_iter: int = 80,
) -> float:
    """Invert Black-76 price → σ via bisection. Raises if premium outside bounds."""
    if premium < 0:
        raise ValueError("premium 不能为负")
    if futures <= 0 or strike <= 0 or years <= 0:
        raise ValueError("F、K、T 必须大于 0")
    df = math.exp(-rate * years)
    # Intrinsic lower bound (discounted)
    if _side(side) == "C":
        intrinsic = df * max(0.0, futures - strike)
    else:
        intrinsic = df * max(0.0, strike - futures)
    if premium < intrinsic - 1e-10:
        raise ValueError("premium 低于贴现内在价值")

    p_lo = black76_price(futures, strike, years, rate, lo, side)
    p_hi = black76_price(futures, strike, years, rate, hi, side)
    if premium < p_lo - 1e-10 or premium > p_hi + 1e-8:
        raise ValueError("premium 超出 [lo,hi] 波动率对应价格区间")

    a, b = lo, hi
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        pm = black76_price(futures, strike, years, rate, mid, side)
        if abs(pm - premium) < tol:
            return mid
        if pm < premium:
            a = mid
        else:
            b = mid
    return 0.5 * (a + b)
