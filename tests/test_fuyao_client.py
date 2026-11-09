# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fuyao_client import (
    bars_from_daily_payload,
    czce_delivery_ticker,
    to_thscode,
)
from market_data import fill_exact_contract_with_fuyao, re_fullmatch_continuous


def test_czce_thscode_mapping():
    assert czce_delivery_ticker("CF2701") == "CF701"
    assert to_thscode("CF2701") == "CF701.CZC"
    assert to_thscode("MA2701") == "MA701.CZC"
    assert to_thscode("RB2505") == "RB2505.SHF"


def test_rejects_continuous_thscode():
    with pytest.raises(ValueError, match="主连"):
        to_thscode("CF0")
    with pytest.raises(ValueError, match="主连"):
        to_thscode("CF00.CZC")
    assert re_fullmatch_continuous("CF0")
    assert not re_fullmatch_continuous("CF2701")


def test_bars_from_payload_maps_ohlc():
    # 2026-11-05 00:00 Asia/Shanghai
    ts = int(datetime(2026, 11, 5, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)
    bars = bars_from_daily_payload(
        {
            "item": [
                {
                    "timestamp": ts,
                    "open_price": 1,
                    "high_price": 3,
                    "low_price": 1,
                    "close_price": 2,
                    "volume": 10,
                    "open_interest": 99,
                }
            ]
        }
    )
    assert len(bars) == 1
    assert bars[0]["date"] == "2026-11-05"
    assert bars[0]["close"] == 2
    assert bars[0]["hold"] == 99
    assert bars[0]["source"] == "fuyao"


def test_fill_skips_when_need_date_present(monkeypatch):
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        return [], {"error": "should_not_call"}

    monkeypatch.setattr("fuyao_client.fetch_exact_contract_daily", boom)
    bars = [{"date": "2026-11-05", "open": 1, "high": 1, "low": 1, "close": 1}]
    out, meta = fill_exact_contract_with_fuyao("CF2701", bars, need_date="2026-11-05")
    assert out == bars
    assert called["n"] == 0
    assert meta["fuyao"] is False


def test_fill_merges_fuyao_gap(monkeypatch):
    def fake_fetch(contract, **_k):
        assert contract == "CF2701"
        return (
            [
                {
                    "date": "2026-11-05",
                    "open": 10,
                    "high": 12,
                    "low": 9,
                    "close": 11,
                    "settle": 11,
                    "source": "fuyao",
                }
            ],
            {"thscode": "CF701.CZC", "error": "", "n": 1},
        )

    monkeypatch.setattr("fuyao_client.fetch_exact_contract_daily", fake_fetch)
    bars = [{"date": "2026-11-04", "open": 1, "high": 1, "low": 1, "close": 1}]
    out, meta = fill_exact_contract_with_fuyao("CF2701", bars, need_date="2026-11-05")
    assert meta["fuyao"] is True
    assert meta["thscode"] == "CF701.CZC"
    assert [b["date"] for b in out] == ["2026-11-04", "2026-11-05"]
    assert out[-1]["close"] == 11
