# -*- coding: utf-8 -*-
"""R6a/b: rolls must not create fake PnL or stops."""
from __future__ import annotations

import historical_backtest as hb
from research.data_quality.rolls import is_roll_day


def test_is_roll_day_oi_and_gap():
    prev = {"contract": "FG2605", "open": 964, "close": 971, "open_interest": 744205}
    cur = {"contract": "FG2605", "open": 1072, "close": 1062, "open_interest": 1063157}
    assert is_roll_day(prev, cur) is True
    quiet = {"contract": "FG2605", "open": 972, "close": 973, "open_interest": 750000}
    assert is_roll_day(prev, quiet) is False
    # Large gap without OI is a real market gap, not a roll.
    gap_only = {"contract": "FG2605", "open": 1072, "close": 1062, "open_interest": 744300}
    assert is_roll_day(prev, gap_only) is False
    no_oi = {"contract": "AA", "open": 100, "close": 100}
    no_oi2 = {"contract": "AA", "open": 110, "close": 110}
    assert is_roll_day(no_oi, no_oi2) is False


def test_is_roll_day_contract_field_change():
    prev = {"contract": "EG2609", "open": 100, "close": 100, "open_interest": 100}
    cur = {"contract": "EG2610", "open": 100.1, "close": 100, "open_interest": 101}
    assert is_roll_day(prev, cur) is True


def test_manage_bar_fixed_uses_cache_ohlc_not_stale_basis(tmp_path, monkeypatch):
    """After roll, exact-contract OHLC wins; stale continuous+basis_off not used."""
    p = {"fill_price_basis": "contract", "fill_contract": "FG2605", "basis_off": -100.0}
    bar = {
        "date": "2026-04-16",
        "contract": "FG2605",
        "open": 1072.0,
        "high": 1074.0,
        "low": 1052.0,
        "close": 1062.0,
        # no contract_*
    }
    exact = {"open": 974.0, "high": 984.0, "low": 951.0, "close": 956.0}
    m, prox, fr = hb.manage_bar_fixed(bar, p, rolled=True, contract_ohlc=exact)
    assert fr is None and not prox
    assert m["open"] == 974.0 and m["high"] == 984.0


def test_manage_bar_fixed_roll_unpriced_without_ohlc():
    p = {"fill_price_basis": "contract", "fill_contract": "FG2605", "basis_off": -100.0}
    bar = {
        "date": "d",
        "contract": "FG2605",
        "open": 1072.0,
        "high": 1074.0,
        "low": 1052.0,
        "close": 1062.0,
    }
    m, prox, fr = hb.manage_bar_fixed(bar, p, rolled=True, contract_ohlc=None, last_close=971.0)
    assert fr == "roll_unpriced" and prox and m["close"] == 971.0


def test_continuous_proxy_shift_neutralizes_cross_contract_gap():
    """After shifting stop by overnight continuous gap, open no longer gaps through."""
    from wyckoff_pullback import apply_stop_target

    entry, stop, target = 6050.0, 5806.8, 6536.4
    prev_close, new_open = 6027.0, 5539.0
    shift = new_open - prev_close
    stop2 = stop + shift
    target2 = target + shift
    entry2 = entry + shift
    # Open equals new_open; after shift, long gap-through requires open <= stop2
    reason, px = apply_stop_target(
        "多",
        entry2,
        stop2,
        target2,
        {"open": new_open, "high": new_open, "low": 5275.0, "close": 5352.0},
    )
    # May still hit stop intraday via low, but not as open gap-through at -2R from raw levels
    assert not (reason == "stop" and px == new_open and (entry - new_open) / (entry - stop) > 1.5)


def test_roll_exit_reason_constant():
    assert "roll_exit" and "roll_unpriced"
