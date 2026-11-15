# -*- coding: utf-8 -*-
"""Black-76 research pricing: price / IV / greeks + FD checks."""
from __future__ import annotations

import math

import pytest

from research.options.pricing.black76 import (
    black76_delta,
    black76_gamma,
    black76_price,
    black76_vega,
    implied_vol,
)
from research.options.specs import (
    SPECS,
    credit_vertical_margin_cny,
    get_spec,
    slip_discount_points,
)


F, K, T, R, SIG = 16000.0, 16000.0, 30.0 / 365.0, 0.02, 0.20


def test_atm_call_put_parity_discounted() -> None:
    """Put-call parity: C − P = e^{−rT}(F − K); ATM → C ≈ P."""
    c = black76_price(F, K, T, R, SIG, "C")
    p = black76_price(F, K, T, R, SIG, "P")
    assert c > 0 and p > 0
    assert abs(c - p) < 1e-8
    assert abs((c - p) - math.exp(-R * T) * (F - K)) < 1e-8


def test_known_atm_price_order() -> None:
    """Higher IV → higher premium; longer T → higher premium (ATM)."""
    c_lo = black76_price(F, K, T, R, 0.10, "C")
    c_hi = black76_price(F, K, T, R, 0.30, "C")
    assert c_hi > c_lo
    c_short = black76_price(F, K, 10 / 365, R, SIG, "C")
    c_long = black76_price(F, K, 60 / 365, R, SIG, "C")
    assert c_long > c_short


def test_implied_vol_roundtrip() -> None:
    prem = black76_price(F, K, T, R, SIG, "C")
    iv = implied_vol(prem, F, K, T, R, "C")
    assert abs(iv - SIG) < 1e-6
    prem_p = black76_price(F, K + 200, T, R, SIG, "P")
    iv_p = implied_vol(prem_p, F, K + 200, T, R, "P")
    assert abs(iv_p - SIG) < 1e-6


def test_delta_call_put_and_bounds() -> None:
    dc = black76_delta(F, K, T, R, SIG, "C")
    dp = black76_delta(F, K, T, R, SIG, "P")
    assert 0.0 < dc < 1.0
    assert -1.0 < dp < 0.0
    # ATM Black-76: delta_call ≈ e^{-rT}/2
    assert abs(dc - math.exp(-R * T) * 0.5) < 0.02
    assert abs(dc - dp - math.exp(-R * T)) < 1e-8


def test_gamma_matches_gamma_wall_wrapper() -> None:
    from gamma_wall import black76_gamma as gw_gamma

    g = black76_gamma(F, K, T, R, SIG)
    assert g > 0
    assert abs(g - gw_gamma(F, K, T, R, SIG)) < 1e-12


def test_gamma_fd_match() -> None:
    """Central FD on call delta ≈ analytical gamma."""
    eps = F * 1e-4
    d_up = black76_delta(F + eps, K, T, R, SIG, "C")
    d_dn = black76_delta(F - eps, K, T, R, SIG, "C")
    g_fd = (d_up - d_dn) / (2.0 * eps)
    g = black76_gamma(F, K, T, R, SIG)
    assert abs(g_fd - g) / g < 1e-3


def test_vega_fd_match() -> None:
    eps = 1e-4
    p_up = black76_price(F, K, T, R, SIG + eps, "C")
    p_dn = black76_price(F, K, T, R, SIG - eps, "C")
    v_fd = (p_up - p_dn) / (2.0 * eps)
    v = black76_vega(F, K, T, R, SIG)
    assert abs(v_fd - v) / v < 1e-3


def test_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        black76_price(0, K, T, R, SIG, "C")
    with pytest.raises(ValueError):
        black76_gamma(F, K, 0, R, SIG)


def test_specs_cf_sr_ma() -> None:
    assert set(SPECS) == {"CF", "SR", "MA"}
    assert get_spec("CF").multiplier == 5.0
    assert get_spec("SR").multiplier == 10.0
    assert get_spec("MA").option_tick == 1.0
    assert get_spec("sr").futures_tick == 1.0


def test_margin_and_slip() -> None:
    # width 200, credit 40, CF mult 5 → max loss 160 × 5 = 800
    assert credit_vertical_margin_cny(width_points=200, credit_points=40, multiplier=5) == 800.0
    assert slip_discount_points(slip_ticks=2, option_tick=5) == 10.0
