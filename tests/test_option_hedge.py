# -*- coding: utf-8 -*-
"""option_hedge: ATM strike_atr_mult=0 must not collapse to default 1.0."""
from __future__ import annotations

from option_hedge import hedge_params, option_strike


def test_hedge_params_atm_zero_preserved() -> None:
    p = hedge_params({"option_hedge": {"strike_atr_mult": 0.0, "premium_atr_mult": 1.5}})
    assert p["strike_atr_mult"] == 0.0
    assert p["premium_atr_mult"] == 1.5


def test_hedge_params_missing_uses_defaults() -> None:
    p = hedge_params({"option_hedge": {}})
    assert p["strike_atr_mult"] == 1.0
    assert p["premium_atr_mult"] == 2.0


def test_option_strike_atm() -> None:
    assert option_strike("多", 1000.0, 20.0, 0.0) == 1000.0
    assert option_strike("空", 1000.0, 20.0, 0.0) == 1000.0
    # 1×ATR: long protective put below entry
    assert option_strike("多", 1000.0, 20.0, 1.0) == 980.0
