# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date

from research.data_quality.calendar import (
    active_front_contract_on_date,
    annotate_bars_with_calendar,
    delivery_flags_for_date,
    estimate_last_trade_day,
    parse_contract_month,
)
from research.execution.contract_pack import front_contract_for, overlay_contract_fills
from research.data_quality import classify_bar


def test_parse_and_last_trade():
    assert parse_contract_month("CF2701") == ("CF", 2027, 1)
    ltd = estimate_last_trade_day(2027, 1, "month_day_10")
    assert ltd == date(2027, 1, 8) or ltd.day <= 10  # weekday on/before 10


def test_delivery_restricted_near_last_trade():
    flags = delivery_flags_for_date("CF", "2027-01-06", front_contract="CF2701")
    assert flags["ok"]
    assert flags["delivery_restricted"] is True
    assert flags["no_new_position"] is True
    assert flags["last_trade_day"] == "2027-01-08"


def test_far_from_delivery_ok():
    flags = delivery_flags_for_date("CF", "2026-09-15", front_contract="CF2701")
    assert flags["delivery_restricted"] is False


def test_annotate_blocks_classify():
    bars = [
        {"date": "2027-01-06", "open": 15000, "high": 15100, "low": 14900, "close": 15050, "volume": 1000},
    ]
    out = annotate_bars_with_calendar("CF", bars, front_contract="CF2701")
    assert out[0].get("delivery_restricted") is True
    q = classify_bar(
        {
            **out[0],
            "code": "CF",
            "atr": 120,
            "bar_date": "2027-01-06",
            "price_basis": "contract",
        },
        asof="2027-01-06",
    )
    assert q["status"] == "VALID_ONLY"
    assert q["tradable"] is False


def test_active_front_rolls_by_date():
    # Aug → CF2609 still alive; after Nov last-trade → CF2701
    assert active_front_contract_on_date("CF", "2026-08-15") == "CF2609"
    assert active_front_contract_on_date("CF", "2026-11-12") == "CF2701"


def test_overlay_contract_fills_marks_coverage():
    series = {
        "CF": {
            "meta": {"code": "CF", "mult": 5, "tick": 5},
            "hist": [
                {"date": "2026-11-05", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10},
                {"date": "2026-11-06", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10},
            ],
        }
    }
    report = overlay_contract_fills(series, month="2701", historical=False)
    assert "CF" in report["symbols"]
    assert series["CF"]["meta"].get("front_contract") == "CF2701"
    assert front_contract_for("CF", "2701") == "CF2701"


def test_overlay_historical_does_not_blanket_observe_month():
    series = {
        "CF": {
            "meta": {"code": "CF", "mult": 5, "tick": 5},
            "hist": [
                {"date": "2026-08-15", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10},
                {"date": "2026-11-12", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10},
            ],
        }
    }
    report = overlay_contract_fills(series, historical=True)
    assert report.get("mode") == "historical_roll"
    contracts = [b.get("contract") for b in series["CF"]["hist"]]
    assert contracts == ["CF2609", "CF2701"]


def test_next_open_prefers_contract_open():
    import historical_backtest as hb

    hist = [
        {"date": "d0", "open": 9, "close": 10},
        {"date": "d1", "open": 12, "contract_open": 11.5, "contract": "CF2701", "close": 11},
    ]
    c = hb.next_open_fill({"entry": 10.0, "stop": 8.0, "target": 14.0}, hist, 0)
    assert c["entry"] == 11.5
    assert c["fill_price_basis"] == "contract"
    assert c["fill_contract"] == "CF2701"
