# -*- coding: utf-8 -*-
"""R7a-D: listing-calendar main_map candidates + injectable contract store + snapshot bundle.

* candidates depend on the day alone: a main_map built on bars cut at T (store cut at T) equals the
  full-window map on every day <= T;
* a replay that reads only the snapshot and its frozen bundle (no local cache) equals the same replay
  on a cache laid out from the same bars, and the frozen R5b reference headline;
* a contract removed from the bundle turns its main_map days into None and feeds the adjusted
  series' fallback count.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab/shadow"))

SNAP = ROOT / "archive/snapshots/bt_input_20261123_da9c8de64ab4.json"
BT = ROOT / "archive/R0/fresh_bt.json"
REF = ROOT / "archive/R5/replay_after_R5b.json"


@pytest.fixture(scope="module")
def world():
    import historical_backtest as hb
    from research.data_quality.contract_store import snapshot_store

    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    store = snapshot_store(snap, SNAP)
    assert store is not None, "snapshot contract bundle missing"
    p = hb._load_cfg()
    meta = {u["code"]: dict(u) for u in p["cfg"]["symbols"] if u["code"] in snap["bars"]}
    return {"hb": hb, "snap": snap, "store": store, "p": p, "meta": meta}


def _series(world, upto=None):
    out = {}
    for c, m in world["meta"].items():
        hist = [b for b in world["snap"]["bars"][c] if upto is None or b["date"] <= upto]
        if hist:
            out[c] = {"meta": dict(m), "hist": copy.deepcopy(hist)}
    return out


def test_listed_contracts_are_calendar_only():
    from research.data_quality.calendar import listed_contracts_on

    on = listed_contracts_on("MA", "2026-06-01")
    assert "MA2609" in on and "MA2610" in on  # beyond the three calendar-nearest months
    assert "MA2605" not in on  # delivered
    assert "MA2707" not in on  # more than 12 months out
    assert listed_contracts_on("MA", "2026-06-01") == on  # pure function of (code, day)


def test_listing_candidates_unaffected_by_truncation(world):
    from research.data_quality.main_map import build_main_map

    full = build_main_map(_series(world), root=world["store"])
    days = sorted({b["date"] for h in world["snap"]["bars"].values() for b in h})
    for cut in (days[-120], days[-60], days[-20], days[-1]):
        part = build_main_map(_series(world, cut), root=world["store"].with_cutoff(cut))
        for c, m in part.maps.items():
            for d, v in m.items():
                assert full.maps[c][d] == v, (cut, c, d, v, full.maps[c][d])
    assert sum(s["none_days"] for s in full.stats.values()) == 0


def _replay(world, monkeypatch, contract_root):
    hb, snap = world["hb"], world["snap"]
    bt = json.loads(BT.read_text(encoding="utf-8"))
    monkeypatch.setattr(hb, "prepare_pack_for_execution", lambda pack, root=None: bt.get("contract_pack") or {})
    monkeypatch.setattr(hb, "load_member_seats", lambda dates, codes: snap["member"])
    monkeypatch.setattr(hb, "load_member_changes", lambda dates, codes: snap["member"])
    monkeypatch.setattr(hb, "lag_member", lambda mm, dates, lag: mm)
    curves = {
        c: ({"carry": v} if not (isinstance(v, dict) and "carry" in v) else v)
        for c, v in (snap.get("carry") or {}).items()
    }
    monkeypatch.setattr(hb, "load_curves", lambda codes: curves)
    monkeypatch.setattr(hb, "lag_curves_carry", lambda cv, dates, lag: cv)
    p = world["p"]
    pack = (_series(world), dict(snap.get("errors") or {}), dict(snap.get("sources") or {}))
    return hb._simulate_cfg(p, p["entry_filter"], pack=pack, contract_root=contract_root)


def test_bundle_replay_equals_cache_replay(world, monkeypatch, tmp_path):
    from research.data_quality.contract_store import CacheContractStore

    import market_data

    def _no_net(*a, **k):
        raise AssertionError("network fetch attempted in an offline test")

    monkeypatch.setattr(market_data, "fetch_sina_exact_contract", _no_net, raising=False)
    store = world["store"]
    # "local full cache": the same bars laid out as .cache/contracts files under an otherwise empty root
    cdir = tmp_path / ".cache" / "contracts"
    cdir.mkdir(parents=True)
    for c in store.known_contracts():
        (cdir / f"{c}.json").write_text(json.dumps({"contract": c, "bars": store.bars(c)}), encoding="utf-8")
    a = _replay(world, monkeypatch, store)
    b = _replay(world, monkeypatch, CacheContractStore(tmp_path))
    assert a.get("ok") and b.get("ok")
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    ref = json.loads(REF.read_text(encoding="utf-8"))
    for k in ("ret_pct", "max_dd_pct", "closed_trades", "gross_ret_pct", "cost_yuan", "exits"):
        assert a.get(k) == ref.get(k), (k, a.get(k), ref.get(k))
    assert a["main_map_full_history"]["none_days_total"] == 0


def test_removed_contract_turns_main_none_and_counts_fallback(world):
    from research.data_quality.adjusted import build_adjusted_pack
    from research.data_quality.contract_store import BundleContractStore
    from research.data_quality.main_map import _snap_contract_bar, build_main_map

    store = world["store"]
    series = _series(world)
    full = build_main_map(series, root=store)
    # a (code, contract) main on >= 5 days that its bar's own snapshot stamp does not price, and with no
    # other listed month inside one tick on those days (otherwise that month is a genuine match)
    pick = None
    for c, m in full.maps.items():
        by_bar = {b["date"]: b for b in series[c]["hist"]}
        for x in sorted({v for v in m.values() if v}):
            days = [
                d for d, v in m.items()
                if v == x and not (str(by_bar[d].get("contract") or "").upper() == x
                                   and _snap_contract_bar(by_bar[d]) is not None)
            ]
            if len(days) < 5:
                continue
            reduced = BundleContractStore({k: store.bars(k) for k in store.known_contracts() if k != x})
            cut = build_main_map({c: series[c]}, root=reduced)
            if all(cut.main(c, d) is None for d in days):
                pick = (c, x, days, reduced, cut)
                break
        if pick:
            break
    assert pick is not None
    code, x, days, reduced, cut = pick
    assert cut.stats[code]["none_days"] >= full.stats[code]["none_days"] + len(days) - 1
    adj_full = build_adjusted_pack({code: series[code]}, full, root=store)[code]
    adj_cut = build_adjusted_pack({code: series[code]}, cut, root=reduced)[code]
    assert sum(adj_cut.fallback) > sum(adj_full.fallback)


def test_formal_prefetch_covers_listing_candidates(tmp_path):
    from research.data_quality.calendar import listed_contracts_on
    from research.data_quality.contract_cache import ensure_listed_contract_bars
    from research.data_quality.contract_store import BundleContractStore

    days = ["2026-11-20", "2026-11-23"]
    series = {"MA": {"hist": [{"date": d, "close": 3000.0} for d in days]}}
    calls: list[str] = []

    def fetcher(c):
        calls.append(c)
        return [{"date": d, "open": 1, "high": 1, "low": 1, "close": 1} for d in days]

    rep = ensure_listed_contract_bars(series, tmp_path, fetcher=fetcher)
    want = sorted(set(listed_contracts_on("MA", days[0])) | set(listed_contracts_on("MA", days[1])))
    assert sorted(calls) == want and rep["requests"] == len(want) and not rep["failed"]
    assert all((tmp_path / ".cache" / "contracts" / f"{c}.json").is_file() for c in want)
    calls.clear()
    rep2 = ensure_listed_contract_bars(series, tmp_path, fetcher=fetcher)
    assert calls == [] and rep2["requests"] == 0 and rep2["cached_n"] == len(want)
    rep3 = ensure_listed_contract_bars(series, BundleContractStore({}), fetcher=fetcher)
    assert calls == [] and rep3.get("skipped")
