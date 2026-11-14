# -*- coding: utf-8 -*-
"""Free bars → TqSdk → iFinD order for continuous history fills."""
from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "ifind_call" not in sys.modules:
    stub = types.ModuleType("ifind_call")
    stub.active_slot = lambda *a, **k: None
    stub.call = lambda *a, **k: {}
    stub.usage_report = lambda: {"count": 0, "calls": []}
    stub.AUTH_TOKEN = ""
    stub.CONFIG = {"auth_token": "", "auth_token_backup": ""}
    sys.modules["ifind_call"] = stub

import historical_backtest as hb  # noqa: E402
import market_data as md  # noqa: E402


def _bar(d: str, c: float = 100.0) -> dict:
    return {"date": d, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1}


def test_fill_main_with_tqsdk_merges_and_tags(monkeypatch):
    expected = md.latest_expected_session_date()
    free = [_bar((expected - timedelta(days=3)).isoformat())]
    tq = [
        _bar((expected - timedelta(days=2)).isoformat(), 101),
        _bar(expected.isoformat(), 102),
    ]

    monkeypatch.setattr(
        "tqsdk_client.load_credentials", lambda root=None: ("u", "p")
    )
    monkeypatch.setattr(
        "tqsdk_client.fetch_daily_bars",
        lambda *a, **k: (tq, "tqsdk:KQ.m@CZCE.CF"),
    )

    bars, meta = md.fill_main_with_tqsdk("CF", free, need_date=expected, root=ROOT)
    assert meta["tqsdk"] is True
    assert meta["tqsdk_n"] == 2
    assert bars[-1]["date"] == expected.isoformat()
    assert bars[-1]["close"] == 102


def test_fetch_history_uses_tqsdk_before_ifind(monkeypatch):
    expected = md.latest_expected_session_date()
    # Enough free bars for indicators, but missing expected session → recent gap path.
    free = [
        _bar((expected - timedelta(days=i)).isoformat(), 100 + i)
        for i in range(100, 0, -1)
    ]
    tq_tail = [_bar(expected.isoformat(), 200)]

    monkeypatch.setattr(md, "load_free_bars", lambda code: (list(free), {"source": "sina", "sina_n": len(free)}))
    monkeypatch.setattr(
        md,
        "fill_main_with_tqsdk",
        lambda code, bars, **kw: (
            bars + tq_tail,
            {"tqsdk": True, "tqsdk_n": 1, "tqsdk_error": "", "tqsdk_source": "tqsdk:KQ.m"},
        ),
    )
    called = {"ifind": 0}

    def _boom(*a, **k):
        called["ifind"] += 1
        raise AssertionError("iFinD must not run when TqSdk filled the gap")

    monkeypatch.setattr(hb, "_fetch_ifind_recent_history", _boom)
    monkeypatch.setattr(hb, "_fetch_ifind_history", _boom)
    monkeypatch.setattr(md, "save_chart_history", lambda code, bars: None)

    bars, meta = hb.fetch_history({"code": "CF", "name": "棉花", "ticker": "CFZL.ZCE"}, n=120)
    assert called["ifind"] == 0
    assert meta.get("tqsdk") is True
    assert "tqsdk" in (meta.get("source") or "")
    assert bars[-1]["date"] == expected.isoformat()


def test_fetch_history_falls_back_to_ifind_when_tq_empty(monkeypatch):
    expected = md.latest_expected_session_date()
    free = [
        _bar((expected - timedelta(days=i)).isoformat(), 100)
        for i in range(100, 0, -1)
    ]
    monkeypatch.setattr(md, "load_free_bars", lambda code: (list(free), {"source": "sina", "sina_n": len(free)}))
    monkeypatch.setattr(
        md,
        "fill_main_with_tqsdk",
        lambda code, bars, **kw: (bars, {"tqsdk": False, "tqsdk_n": 0, "tqsdk_error": "no-auth"}),
    )
    monkeypatch.setattr(hb, "_ifind_ready", lambda: True)
    monkeypatch.setattr(
        hb,
        "_fetch_ifind_recent_history",
        lambda u, exp: [_bar(exp.isoformat(), 300)],
    )
    monkeypatch.setattr(md, "save_chart_history", lambda code, bars: None)

    bars, meta = hb.fetch_history({"code": "CF", "name": "棉花", "ticker": "CFZL.ZCE"}, n=120)
    assert meta.get("ifind") is True
    assert "ifind" in (meta.get("source") or "")
    assert bars[-1]["close"] == 300
