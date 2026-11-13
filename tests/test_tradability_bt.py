# -*- coding: utf-8 -*-
"""P0-b: simulate blocks non-PASS fills; Base/Stress contrast; config stamp."""
from __future__ import annotations

import math
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "ifind_call" not in sys.modules:
    stub = types.ModuleType("ifind_call")
    stub.active_slot = lambda *a, **k: None
    stub.call = lambda *a, **k: {}
    stub.usage_report = lambda: {"count": 0, "calls": []}
    sys.modules["ifind_call"] = stub

import historical_backtest as hb  # noqa: E402
from path_a_filters import fill_cost  # noqa: E402

N = 140


def _dates(n=N):
    from datetime import date, timedelta

    d, out = date(2025, 1, 1), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _pack(*, limit_lock: bool = False, zero_vol: bool = False):
    dates = _dates()
    series = {}
    for k, code in enumerate(("AA", "BB", "CC")):
        hist = []
        for i, d in enumerate(dates):
            c = 1000 * (1 + 0.004 * i) + 15 * math.sin(i / 3 + k)
            row = {
                "date": d,
                "open": c - 2,
                "high": c + 8,
                "low": c - 8,
                "close": c,
                "volume": 0 if zero_vol else 1000,
            }
            if limit_lock and i >= 60:
                row.update(
                    {
                        "open": c,
                        "high": c,
                        "low": c,
                        "close": c,
                        "limit_status": "涨停",
                        "volume": 0,
                    }
                )
            hist.append(row)
        series[code] = {
            "meta": {"code": code, "name": code, "mult": 10, "tick": 1, "bucket": code, "fee_yuan": 1.0},
            "hist": hist,
        }
    return series, {}, {}


def _run(monkeypatch, **kw):
    monkeypatch.setattr(hb, "entry_block", lambda *a, **k: None)
    monkeypatch.setattr(hb, "seat_decision", lambda direction, book: (None, "t"))
    monkeypatch.setattr(
        hb,
        "load_member_seats",
        lambda dates, codes: {c: {d: {"asof": d} for d in dates} for c in codes},
    )
    monkeypatch.setattr(hb, "load_curves", lambda codes, **k: {})
    pk = kw.pop("pack", None) or _pack()
    return hb.simulate(
        [v["meta"] for v in pk[0].values()],
        200_000,
        mode="base",
        pack=pk,
        min_r20=0.5,
        min_r60=0.5,
        **kw,
    )


def test_entry_fill_allowed_blocks_limit():
    ok, q = hb.entry_fill_allowed(
        "CF",
        {
            "date": "2026-10-27",
            "open": 15000,
            "high": 15000,
            "low": 15000,
            "close": 15000,
            "volume": 0,
            "limit_status": "涨停",
        },
        {"code": "CF"},
        side="空",
        asof="2026-10-27",
    )
    assert ok is False
    assert q["status"] == "VALID_ONLY"


def test_limit_lock_blocks_new_entries(monkeypatch):
    base = _run(monkeypatch, pack=_pack())
    locked = _run(monkeypatch, pack=_pack(limit_lock=True))
    assert base.get("ok") and (base.get("closed_trades") or 0) > 0
    assert locked.get("ok")
    assert (locked.get("closed_trades") or 0) == 0
    assert locked.get("quality_blocks")
    assert any(str(k).startswith("quality:") for k in (locked.get("quality_blocks") or {}))


def test_simulate_config_stamp_and_schema(monkeypatch):
    out = _run(monkeypatch)
    assert out["schema_version"] == hb.SCHEMA_VERSION
    assert out.get("config_version")
    assert out["config_version"].get("execution_rules_sha256")
    assert out.get("cost_scenario") == "base"
    assert out.get("fill_series") == "continuous_proxy"
    assert out.get("enforce_tradability") is True


def test_fee_mult_scales_posted_fee():
    meta = {"mult": 10, "tick": 1, "fee_yuan": 2.0}
    base = fill_cost(meta, 1000, 3, slippage_ticks=0.0, fee_mult=1.0)
    stress = fill_cost(meta, 1000, 3, slippage_ticks=0.0, fee_mult=1.25)
    assert base == 6.0
    assert stress == 7.5


def test_stress_scenario_higher_slippage_cost(monkeypatch):
    base = _run(monkeypatch, cost_scenario="base")
    stress = _run(monkeypatch, cost_scenario="stress")
    assert base["slippage_ticks"] == 1.0
    assert stress["slippage_ticks"] == 2.0
    # Same path with higher slip → higher or equal total cost when trades exist
    if (base.get("closed_trades") or 0) > 0:
        assert stress["cost_yuan"] >= base["cost_yuan"]


def test_attach_cost_contrast(monkeypatch):
    p = {
        "cfg": {"symbols": []},
        "equity0": 200_000,
        "compound": True,
        "risk_pct": 2.0,
        "l1_mult": 1.0,
        "max_positions": 3,
        "max_gross_pct": 50,
        "max_port_risk": 8,
        "max_per_bucket": 1,
        "min_r20": 0.5,
        "min_r60": 0.5,
        "min_lots": 0,
        "option_hedge": False,
        "premium_atr_mult": 0.0,
        "strike_atr_mult": 0.0,
        "reward_rr": 2.0,
        "stop_atr_mult": 0.8,
        "carry_bypass": {"enabled": False},
        "vol_bypass": {"enabled": False},
        "availability_lag": 1,
        "fill_price": "next_open",
        "cost_scenario": "base",
    }
    monkeypatch.setattr(hb, "entry_block", lambda *a, **k: None)
    pk = _pack()
    primary = hb.simulate(
        [v["meta"] for v in pk[0].values()],
        200_000,
        mode="base",
        pack=pk,
        min_r20=0.5,
        min_r60=0.5,
    )
    hb.attach_cost_scenario_contrast(primary, p, "base", pack=pk, scenarios=("stress",))
    contrast = primary["cost_scenario_contrast"]
    assert contrast["ok"] is True
    assert "base" in contrast["rows"] and "stress" in contrast["rows"]
    assert contrast["rows"]["stress"]["slippage_ticks"] == 2.0
    # Primary KPI unchanged (still base)
    assert primary["cost_scenario"] == "base"
    assert primary["ret_pct"] == contrast["rows"]["base"]["ret_pct"]
