# -*- coding: utf-8 -*-
from ema_cross import ema_cross_series, ema_series


def test_ema_series_seed_and_rise():
    closes = [float(i) for i in range(1, 31)]
    e = ema_series(closes, 10)
    assert e[9] is not None
    assert e[-1] is not None and e[-1] > e[9]


def test_ema_cross_detects_crossunder_after_drop():
    hist = []
    px = 100.0
    for _ in range(40):
        px += 0.5
        hist.append({"close": px, "high": px + 1, "low": px - 1, "open": px})
    for _ in range(25):
        px -= 1.5
        hist.append({"close": px, "high": px + 1, "low": px - 1, "open": px})
    sig = ema_cross_series(hist, fast=10, slow=20)
    assert any(x and x["short"] for x in sig)
