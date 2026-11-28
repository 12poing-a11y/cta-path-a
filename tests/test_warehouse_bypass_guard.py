# -*- coding: utf-8 -*-
"""EM bypass guard: stale or zero-tail eastmoney rows must not be published as current receipts."""
from __future__ import annotations

from datetime import date

from warehouse_receipt import _bypass_stale_reason

ASOF = date(2026, 11, 27)  # Friday


def test_same_day_row_is_usable():
    assert _bypass_stale_reason({"date": "2026-11-27", "inventory": 3967.0}, ASOF) is None


def test_one_business_day_lag_is_usable():
    assert _bypass_stale_reason({"date": "2026-11-26", "inventory": 4415.0}, ASOF) is None


def test_zero_tail_before_asof_is_rejected():
    # P / JM case: last EM row is 0 on 11-23, four business days before 11-27.
    assert _bypass_stale_reason({"date": "2026-11-23", "inventory": 0.0}, ASOF) == "em_zero_no_follow_up"


def test_stale_nonzero_row_is_rejected():
    reason = _bypass_stale_reason({"date": "2026-11-20", "inventory": 1359.0}, ASOF)
    assert reason is not None and reason.startswith("em_stale_")


def test_unparsed_date_is_rejected():
    assert _bypass_stale_reason({"date": None, "inventory": 5.0}, ASOF) == "em_date_unparsed"


def test_weekend_gap_does_not_count_as_stale():
    # Friday 11-27 vs Wednesday 11-25 -> 2 business days (Thu, Fri): still usable.
    assert _bypass_stale_reason({"date": "2026-11-25", "inventory": 4515.0}, ASOF) is None
