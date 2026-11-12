# -*- coding: utf-8 -*-
from supertrend import atr_wilder_series, supertrend_series


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "date": "2026-01-01"}


def test_supertrend_emits_buy_after_uptrend():
    hist = []
    px = 100.0
    for _ in range(30):
        px += 0.2
        hist.append(_bar(px, px + 0.5, px - 0.5, px))
    # sharp drop to force sell then recovery buy
    for _ in range(15):
        px -= 2.0
        hist.append(_bar(px, px + 0.5, px - 0.8, px))
    for _ in range(20):
        px += 2.5
        hist.append(_bar(px, px + 0.8, px - 0.5, px))
    st = supertrend_series(hist, atr_period=10, multiplier=3.0)
    buys = sum(1 for x in st if x and x["buy"])
    sells = sum(1 for x in st if x and x["sell"])
    assert sells >= 1
    assert buys >= 1
    atrs = atr_wilder_series(hist, 10)
    assert atrs[-1] is not None and atrs[-1] > 0
