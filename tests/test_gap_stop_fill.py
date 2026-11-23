# -*- coding: utf-8 -*-
"""R3: gap-through stop fills at open; target=None skips take-profit."""
from __future__ import annotations

from wyckoff_pullback import apply_stop_target


def test_long_gap_through_stop_fills_at_open():
    # stop=98, open=96 already through, low=95
    reason, px = apply_stop_target(
        "多", 100.0, 98.0, 104.0, {"open": 96.0, "high": 97.0, "low": 95.0, "close": 96.5}
    )
    assert (reason, px) == ("stop", 96.0)


def test_short_gap_through_stop_fills_at_open():
    reason, px = apply_stop_target(
        "空", 100.0, 102.0, 96.0, {"open": 104.0, "high": 105.0, "low": 103.0, "close": 104.5}
    )
    assert (reason, px) == ("stop", 104.0)


def test_intraday_touch_without_gap_fills_at_stop():
    reason, px = apply_stop_target(
        "多", 100.0, 98.0, 104.0, {"open": 100.0, "high": 101.0, "low": 97.0, "close": 99.0}
    )
    assert (reason, px) == ("stop", 98.0)
    reason, px = apply_stop_target(
        "空", 100.0, 102.0, 96.0, {"open": 100.0, "high": 103.0, "low": 99.0, "close": 101.0}
    )
    assert (reason, px) == ("stop", 102.0)


def test_target_none_does_not_take_profit():
    reason, px = apply_stop_target(
        "多", 100.0, 98.0, None, {"open": 100.0, "high": 110.0, "low": 99.0, "close": 109.0}
    )
    assert reason is None and px == 109.0


def test_missing_open_uses_close():
    # open missing → o=close=96 ≤ stop=98 → gap stop at close
    reason, px = apply_stop_target(
        "多", 100.0, 98.0, 104.0, {"high": 97.0, "low": 95.0, "close": 96.0}
    )
    assert (reason, px) == ("stop", 96.0)
