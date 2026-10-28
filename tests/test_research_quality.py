# -*- coding: utf-8 -*-
from datetime import date

from research_quality import (
    atr_close_ok,
    validate_backtest_meta,
    validate_bar_date,
    validate_signals,
)


def test_atr_close_ok():
    assert atr_close_ok(100.0, 2.0) is True
    assert atr_close_ok(100.0, 40.0) is False
    assert atr_close_ok(0, 1) is False


def test_bar_date_rejects_weekend_and_future():
    ok, _ = validate_bar_date("20261027", asof="20261027")  # Tue
    assert ok
    ok, reason = validate_bar_date("20261025", asof="20261027")  # Sun
    assert not ok and reason == "bar_date_weekend"
    ok, reason = validate_bar_date("20261030", asof="20261027")
    assert not ok and reason == "bar_date_future"


def test_validate_signals_hard_fail_on_future():
    rows = [
        {"code": "RB", "close": 3500, "atr": 40, "bar_date": "20261027"},
        {"code": "CU", "close": 70000, "atr": 800, "bar_date": "20990101"},
    ]
    q = validate_signals(rows, asof="20261027")
    assert q["ok"] is False
    assert "CU" in q["bad_codes"]


def test_validate_backtest_meta_dense_days():
    q = validate_backtest_meta(
        {"start": "2025-10-31", "end": "2026-10-31", "trade_days": 367},
        today=date(2026, 10, 28),
    )
    assert q["ok"] is False
    assert "trade_days_too_dense" in q["failures"] or "trade_days_looks_like_calendar" in q["failures"]
