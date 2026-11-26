# -*- coding: utf-8 -*-
"""R8 long-sample entry + candidate C.

* Candidate C (monthly notional pool) is tested on CONSTRUCTED data only (never on the 216-day window).
* The default (local) path must reproduce the frozen 216-day result bit for bit; the guard is official-path only.
* Official-data tests are skipped when the (git-ignored) raw official files are not on disk.
"""
from __future__ import annotations

import copy
import json
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

if "ifind_call" not in sys.modules:  # import without IFIND_AUTH_TOKEN; no network
    _stub = types.ModuleType("ifind_call")
    _stub.active_slot = lambda *a, **k: None
    _stub.call = lambda *a, **k: {}
    _stub.usage_report = lambda: {"count": 0, "calls": []}
    sys.modules["ifind_call"] = _stub

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "archive" / "R8"))
sys.path.insert(0, str(ROOT / "lab" / "shadow"))

import historical_backtest as hb  # noqa: E402
import long_sample as ls  # noqa: E402
from research.data_quality.contract_store import BundleContractStore  # noqa: E402
from research.data_quality.main_map import MainMap  # noqa: E402
from research.execution import entry_filters as ef  # noqa: E402

RAW = ROOT / "archive" / "R8" / "raw_contract" / "shfe"
needs_raw = pytest.mark.skipif(not RAW.exists() or not any(RAW.glob("2025*.gz")), reason="raw official files not on disk")


# ------------------------------------------------------------------------------------------------ pool (constructed)
def _bars(dates, settle=None, close=100.0):
    return [{"date": d, "close": close, "settle": settle} for d in dates]


def test_pool_boundary_is_inclusive_and_fixed_for_the_month():
    # E0 = 1,000,000 -> cap 250,000.  XA: 25,000 x 10 = 250,000 (== cap -> IN).  XB: 25,001 x 10 (> cap -> OUT).
    bars = {"XA": _bars(["2020-01-30", "2020-01-31", "2020-02-03"], settle=25000.0),
            "XB": _bars(["2020-01-30", "2020-01-31", "2020-02-03"], settle=25001.0)}
    pool = ef.MonthlyNotionalPool(equity0=1_000_000.0, mult={"XA": 10.0, "XB": 10.0}, bars=bars)
    pool.begin_day("2020-02-03", 999_999.0)  # first month of the run: initial capital, NOT the passed equity
    assert pool.allows("XA", "2020-02-03") and not pool.allows("XB", "2020-02-03")
    pool.begin_day("2020-02-04", 5_000_000.0)  # same month: equity changes must not re-compute the pool
    assert pool.allows("XA", "2020-02-04") and not pool.allows("XB", "2020-02-04")


def test_pool_uses_prior_month_end_equity_and_prior_month_end_settle():
    bars = {"XA": [{"date": "2020-01-31", "close": 1.0, "settle": 20000.0}, {"date": "2020-02-28", "close": 1.0, "settle": 20000.0},
                   {"date": "2020-03-02", "close": 1.0, "settle": 99999.0}]}
    pool = ef.MonthlyNotionalPool(equity0=1_000_000.0, mult={"XA": 10.0}, bars=bars)
    pool.begin_day("2020-02-03", 1_000_000.0)
    assert pool.allows("XA", "2020-02-03")  # 200,000 <= 250,000
    pool.begin_day("2020-03-02", 700_000.0)  # E = 700,000 -> cap 175,000 < 200,000 (Feb-end settle, not Mar-2's 99,999)
    assert not pool.allows("XA", "2020-03-02")
    rep = pool.report()
    assert [m["month"] for m in rep["months"]] == ["2020-02", "2020-03"]
    assert rep["months"][1]["E"] == 700_000.0 and rep["months"][1]["excluded"] == ["XA"]


def test_pool_signal_day_month_governs_not_the_fill_day():
    bars = {"XA": _bars(["2020-01-31"], settle=1000.0)}
    pool = ef.MonthlyNotionalPool(equity0=1_000_000.0, mult={"XA": 1.0}, bars=bars)
    pool.begin_day("2020-02-28", 1_000_000.0)
    assert pool.allows("XA", "2020-02-28")  # signal on the last day of Feb is judged on Feb's pool (T+1 fill may be March)
    assert not pool.allows("XA", "2020-03-02")  # a day of a month whose pool was not built is never allowed


def test_pool_settle_fallback_to_close_and_no_prior_bar():
    bars = {"XA": [{"date": "2020-01-31", "close": 1000.0, "settle": None}], "XB": [{"date": "2020-01-31", "close": 5.0, "settle": 0}],
            "XC": [{"date": "2020-02-03", "close": 1.0, "settle": 1.0}]}
    pool = ef.MonthlyNotionalPool(equity0=1_000_000.0, mult={"XA": 1.0, "XB": 1.0, "XC": 1.0}, bars=bars)
    pool.begin_day("2020-02-03", 1_000_000.0)
    m = pool.report()["months"][0]
    assert {x["code"] for x in m["settle_fallback_close"]} == {"XA", "XB"}  # missing / zero settle -> prior month-end close
    assert m["no_prior_bar"] == ["XC"] and not pool.allows("XC", "2020-02-03")  # listed after the month end: outside the pool
    assert pool.allows("XA", "2020-02-03") and pool.allows("XB", "2020-02-03")


def test_pool_reports_months_without_nonferrous():
    bars = {c: _bars(["2020-01-31"], settle=1_000_000.0) for c in ("AG", "AL", "AU", "CU", "NI")}
    bars["RB"] = _bars(["2020-01-31"], settle=10.0)
    pool = ef.MonthlyNotionalPool(equity0=1_000_000.0, mult={**{c: 1.0 for c in bars}}, bars=bars)
    pool.begin_day("2020-02-03", 1_000_000.0)
    rep = pool.report()
    assert rep["months_nonferrous_empty"] == ["2020-02"]
    assert rep["months"][0]["pool"] == ["RB"]


# ------------------------------------------------------------------------------------------------ engine hooks (constructed)
def _synthetic_pack(n=200, only=None):
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    base = {u["code"]: u for u in cfg["symbols"]}
    spec = [("XA", "CF", 5.0, 10000.0), ("XB", "RB", 100.0, 3000.0), ("XC", "TA", 10.0, 5000.0)]  # notional 50k / 300k / 50k
    series, maps = {}, {}
    d0 = date(2020, 1, 1)
    days, d = [], d0
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    for code, like, mult, px0 in spec:
        if only and code not in only:
            continue
        meta = dict(base[like], code=code, mult=mult, tick=1.0)
        hist, prev = [], px0
        for i, ds in enumerate(days):
            c = px0 * (1.006 ** i)
            hist.append({"date": ds, "open": prev, "high": max(prev, c) * 1.002, "low": min(prev, c) * 0.998, "close": c, "volume": 1000.0,
                         "oi": 1000.0, "settle": c})
            prev = c
        series[code] = {"meta": meta, "hist": hist}
        maps[code] = {b["date"]: code + "2012" for b in hist}
    mm = MainMap(maps=maps, stats={c: {"days": len(h["hist"]), "matched": len(h["hist"]), "none_days": 0, "coverage": 1.0} for c, h in series.items()})
    return series, mm, cfg


def _run_synth(kind, equity=1_000_000.0, only=None):
    series, mm, cfg = _synthetic_pack(only=only)
    p = hb._load_cfg()
    p["cfg"] = {**cfg, "symbols": [s["meta"] for s in series.values()]}
    p["equity0"] = equity
    p["carry_bypass"] = {"enabled": False}
    store = BundleContractStore({})
    lsd = {"main_map": mm, "skip_contract_overlay": True, "no_minute": True}
    if kind == "C":
        lsd["candidate_pool"] = ef.MonthlyNotionalPool(equity0=equity, mult={c: float(s["meta"]["mult"]) for c, s in series.items()},
                                                        bars={c: s["hist"] for c, s in series.items()})
    return hb._simulate_cfg(p, "base", pack=(series, {}, {}), contract_root=store, long_sample=lsd)


def test_candidate_c_excludes_big_notional_symbol_on_constructed_data():
    a, c = _run_synth("A", only=("XB",)), _run_synth("C")  # control: with XB alone the book has room for it
    assert any(t["code"] == "XB" for t in a["closed_pnls"]) or "XB" in a["final_positions"], "A must be able to trade XB (control)"
    assert any(t["code"] in ("XA", "XC") for t in c["closed_pnls"]), "C still trades the in-pool symbols"
    assert not any(t["code"] == "XB" for t in c["closed_pnls"]) and "XB" not in c["final_positions"]
    rep = c["long_sample"]["pool"]
    assert all("XB" in m["excluded"] and "XB" not in m["pool"] for m in rep["months"])
    assert c["long_sample"]["pool_blocked_signals"].get("XB", 0) > 0
    assert "long_sample" in a and a["long_sample"]["pool"] is None  # A has no pool; formal output has no such key (below)


def test_formal_output_has_no_long_sample_key_and_default_hooks_are_inert():
    snap = ROOT / "archive" / "snapshots" / "bt_input_20261125_05dade0b049c.json"
    if not snap.exists():
        pytest.skip("frozen snapshot missing")
    out = ls.run_local_216(snap, ROOT / "archive" / "R8" / "E1000k" / "result.json", {"equity0": 1_000_000.0})
    assert "long_sample" not in out


# ------------------------------------------------------------------------------------------------ 216-day regression
def _canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)


@pytest.mark.parametrize("group,overrides", [("E1000k", {"equity0": 1_000_000.0}), ("F2", {"equity0": 1_000_000.0, "filter_atr_spike": True})])
def test_local_default_path_reproduces_the_frozen_216_day_result_bit_for_bit(group, overrides):
    bt = ROOT / "archive" / "R8" / group / "result.json"
    if not bt.exists():
        pytest.skip("frozen result missing")
    live = json.loads(bt.read_text(encoding="utf-8"))
    snap = ROOT / live["input_snapshot"]["path"]
    saved = {k: getattr(hb, k) for k in ("prepare_pack_for_execution", "load_member_seats", "load_curves", "lag_curves_carry")}
    out = ls.run_group(group, data_source="local", snap_path=snap, bt_path=bt, overrides=overrides)
    assert _canon(out["closed_pnls"]) == _canon(live["closed_pnls"])
    assert _canon(out["equity_curve"]) == _canon(live["equity_curve"])
    for k in ("ret_pct", "max_dd_pct", "cost_yuan", "closed_trades", "equity_end"):
        assert out[k] == live[k], k
    assert all(getattr(hb, k) is v for k, v in saved.items()), "hb globals patched by the replay must be restored"


def test_guard_is_official_path_only():
    with pytest.raises(ValueError):
        ls.run_group("A1000k", data_source="local", guard_pct=0.05, snap_path="x", bt_path="y")
    with pytest.raises(ValueError):
        ls.run_group("A1000k", data_source="nope")
    with pytest.raises(ValueError):
        ls.run_group("Z1000k", data_source="official")


# ------------------------------------------------------------------------------------------------ guard (constructed)
def test_guard_blocks_thin_one_tick_contract_and_default_is_unguarded():
    from research.data_quality.calendar import listed_contracts_on

    day = "2024-03-04"
    c1, c2 = listed_contracts_on("CU", day)[:2]
    # the thin contract matches the continuous close (within 1 tick); the real main does not (snapshot-type mismatch)
    rows = {c1: [{"date": day, "open": 70000.0, "high": 70100.0, "low": 69900.0, "close": 70020.0, "volume": 50.0}],
            c2: [{"date": day, "open": 70000.0, "high": 70100.0, "low": 69900.0, "close": 70200.0, "volume": 100000.0}]}
    store = BundleContractStore(rows)
    cont = [{"date": day, "open": 70000.0, "high": 70100.0, "low": 69900.0, "close": 70020.0}]
    vol = {(c1, day): 50.0, (c2, day): 100000.0}
    ref = lambda c, d: vol.get((c, d), 0)  # noqa: E731
    assert ls.guarded_main_series("CU", cont, store, 10.0, 0.0, ref)[day] == c1  # engine rule: thin contract wins on price
    assert ls.guarded_main_series("CU", cont, store, 10.0, 0.05, ref)[day] is None  # guarded: unidentified (carry, no roll)
    vol[(c1, day)] = 5000.0  # exactly 5% of the max -> allowed (the guard is strictly "< 5%")
    assert ls.guarded_main_series("CU", cont, store, 10.0, 0.05, ref)[day] == c1
    vol.update({(c1, day): 0.0, (c2, day): 0.0})  # no volume anywhere: the guard cannot judge -> not applied
    assert ls.guarded_main_series("CU", cont, store, 10.0, 0.05, ref)[day] == c1


def test_trade_net_pnl_counts_every_fill_once():
    meta = {"mult": 10.0, "tick": 1.0, "fee_yuan": 2.0, "fee_rate": None}
    t = {"direction": "多", "lots": 2, "entry": 105.0, "entry_orig": 100.0, "exit": 120.0,
         "roll_events": [{"status": "shifted", "old_open": 110.0, "new_open": 115.0}, {"status": "unpriced_cont", "date": "x"}]}
    n = ls.trade_net_pnl(t, meta, 1.0, 1.0)
    assert n["gross"] == (120.0 - 105.0) * 2 * 10.0 and n["n_rolls"] == 1
    fills = [hb.fill_cost(meta, px, 2, slippage_ticks=1.0, fee_mult=1.0) for px in (100.0, 110.0, 115.0, 120.0)]  # entry, old, new, exit
    assert abs(n["cost"] - sum(fills)) < 1e-9


# ------------------------------------------------------------------------------------------------ official data (skipped without raw files)
@needs_raw
def test_guard_zero_replica_equals_engine_build_main_map():
    from contract_loader import load_all
    from research.data_quality.main_map import build_main_map

    by = load_all()
    store = BundleContractStore(ls.bundle_of(by))
    cfg = {u["code"]: u for u in json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))["symbols"]}
    for code in ("CU", "RB", "SR"):
        hist = [b for b in json.loads((ROOT / ".cache" / "history" / f"{code}0.json").read_text(encoding="utf-8"))
                if "2024-01-02" <= str(b["date"])[:10] <= "2024-12-31"]
        eng = build_main_map({code: {"hist": hist, "meta": cfg[code]}}, root=store).maps[code]
        rep = ls.guarded_main_series(code, hist, store, float(cfg[code]["tick"]), 0.0, lambda c, d: 0)
        assert {d: m for d, m in rep.items()} == {d: m for d, m in eng.items()}


@needs_raw
def test_official_pack_is_stitched_from_the_identified_main_and_truncated_at_the_window_end():
    pack, mm, store, info = ls.build_official_pack(w1="2016-09-30", codes=["CU", "RB"])
    assert info["max_loaded_date"] <= "2016-09-30"
    for code, s in pack[0].items():
        ds = [b["date"] for b in s["hist"]]
        assert ds == sorted(set(ds))
        for b in s["hist"]:
            assert mm.main(code, b["date"]) == b["contract"]
            assert store.by_date(b["contract"])[b["date"]]["close"] == b["close"]
