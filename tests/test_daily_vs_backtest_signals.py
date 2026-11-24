# -*- coding: utf-8 -*-
"""R5a: the daily report and the backtest must derive the same entry candidates.

Offline: bars, seat / carry books come from the frozen snapshot; month-contract bars come from the
snapshot's frozen contract bundle (variant ``bundle``: the backtest sees the whole bundle, the daily
run of day T sees it cut at T) or from an empty directory (variant ``empty_cache``: both sides fall
back to the raw continuous series).  No local cache is read and nothing is fetched.

For each of the last 40 trading days of the window, ``daily_update.compute_signals`` sees ONLY the
bars up to that day (what the real daily run would have) and its per-code result must equal
``simulate``'s candidate verdicts (``candidate_log``): direction, r20, r60, ATR, stop distance,
lots and every filter verdict, float tolerance 1e-9.  The backtest's day-held positions are then
injected as ``held`` and the post-caps selection must match.
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
pytestmark = pytest.mark.skipif(not (SNAP.exists() and BT.exists()), reason="snapshot / R0 bt missing")

TOL = 1e-9
N_DAYS = 40


def _close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= TOL


@pytest.fixture(scope="module", params=["bundle", "empty_cache"])
def world(request, tmp_path_factory):
    import historical_backtest as hb

    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    bt = json.loads(BT.read_text(encoding="utf-8"))
    mp = pytest.MonkeyPatch()
    mp.setattr(hb, "prepare_pack_for_execution", lambda pack, root=None: bt.get("contract_pack") or {})
    mp.setattr(hb, "load_member_seats", lambda dates, codes: snap["member"])
    mp.setattr(hb, "load_member_changes", lambda dates, codes: snap["member"])
    mp.setattr(hb, "lag_member", lambda mm, dates, lag: mm)  # snapshot books are already lagged
    curves = {
        c: ({"carry": v} if not (isinstance(v, dict) and "carry" in v) else v)
        for c, v in (snap.get("carry") or {}).items()
    }
    mp.setattr(hb, "load_curves", lambda codes: curves)
    mp.setattr(hb, "lag_curves_carry", lambda cv, dates, lag: cv)

    def _no_net(*a, **k):
        raise AssertionError("network fetch attempted in an offline test")

    import market_data

    mp.setattr(market_data, "fetch_sina_exact_contract", _no_net, raising=False)
    if request.param == "bundle":
        from research.data_quality.contract_store import snapshot_store

        root = snapshot_store(snap, SNAP)
        assert root is not None, "snapshot contract bundle missing"
    else:
        root = tmp_path_factory.mktemp("empty_root")
    p = hb._load_cfg()
    series = {}
    for u in p["cfg"]["symbols"]:
        if u["code"] in snap["bars"]:
            series[u["code"]] = {"meta": dict(u), "hist": copy.deepcopy(snap["bars"][u["code"]])}
    pack = (series, dict(snap.get("errors") or {}), dict(snap.get("sources") or {}))
    log: list = []
    hb._simulate_cfg(p, p["entry_filter"], pack=pack, candidate_log=log, contract_root=root)
    yield {"hb": hb, "p": p, "series": series, "log": log, "root": root, "snap": snap, "curves": curves,
           "variant": request.param}
    mp.undo()


def _daily(world, day, *, observe_min_lots=0):
    import daily_update as du

    hb, p, series = world["hb"], world["p"], world["series"]
    bars = {}
    for c, s in series.items():
        hist = s["hist"]
        k = max((j for j, b in enumerate(hist) if b["date"] <= day), default=None)
        if k is not None:
            bars[c] = copy.deepcopy(hist[: k + 1])
    universe = [dict(s["meta"]) for c, s in series.items() if c in bars]
    snapm = world["snap"]["member"]
    bypass = hb.carry_bypass_cfg(p.get("carry_bypass"))
    vbypass = hb.vol_bypass_cfg(p.get("vol_bypass"))
    entry = next(e for e in world["log"] if e["date"] == day)
    sigs, info = du.compute_signals(
        universe,
        bars,
        mode=p["entry_filter"],
        bypass=bypass,
        vbypass=vbypass,
        curves=world["curves"],
        member_loader=lambda dates, codes: snapm,
        risk_budget=entry["day_risk"],
        contract_root=world["root"].with_cutoff(day) if world["variant"] == "bundle" else world["root"],
        min_seat_days=p.get("min_seat_days", hb.MIN_SEAT_DAYS),
        observe_min_lots=observe_min_lots,
    )
    return sigs, info, bars, entry


def _days(world):
    trade = [e["date"] for e in world["log"]]
    return trade[-N_DAYS:]


def test_config_agrees_between_daily_and_backtest(world):
    import daily_update as du

    p = world["p"]
    assert du.MIN_R20_PCT == p["min_r20"] and du.MIN_R60_PCT == p["min_r60"]
    assert du.STOP_ATR_MULT == p["stop_atr_mult"] and du.REWARD_RR == p["reward_rr"]
    assert du.MAX_POSITIONS == p["max_positions"] and du.MAX_PER_BUCKET == p["max_per_bucket"]
    assert du.MAX_GROSS_PCT == p["max_gross_pct"] and du.MAX_PORT_RISK_PCT == p["max_port_risk"]
    assert du._entry_mode() == p["entry_filter"]
    hb = world["hb"]
    assert du._carry_bypass() == hb.carry_bypass_cfg(p.get("carry_bypass"))
    assert du._vol_bypass() == hb.vol_bypass_cfg(p.get("vol_bypass"))


def test_window_has_enough_days(world):
    assert len(world["log"]) >= N_DAYS


def test_candidates_equal_per_day(world):
    n_cmp = n_cand = n_blocked = 0
    for day in _days(world):
        sigs, info, bars, entry = _daily(world, day)
        for code, v in entry["verdicts"].items():
            res = info["core"].get(code)
            assert res is not None, (day, code)
            assert bars[code][-1]["date"] == day
            n_cmp += 1
            for k in ("status", "aligned", "gate_ok", "direction", "blocked", "block_kind", "seat_label",
                      "seat_short", "vol_reason", "lots"):
                assert res.get(k) == v.get(k), (day, code, k, res.get(k), v.get(k))
            for k in ("r20", "r60", "atr"):
                assert _close(res.get(k), v.get(k)), (day, code, k, res.get(k), v.get(k))
            cy = None if res["carry"] is None else res["carry"]["label"]
            assert cy == v["carry"], (day, code, "carry", cy, v["carry"])
            sd = None if res["sizing"] is None else res["sizing"]["stop_dist"]
            td = None if res["sizing"] is None else res["sizing"]["target_dist"]
            assert _close(sd, v["stop_dist"]) and _close(td, v["target_dist"]), (day, code)
            n_blocked += res["status"] == "blocked"
        # candidate set handed to the caps
        sim_c = {c["code"]: c for c in entry["cands"]}
        day_c = {
            c: r["candidate"] for c, r in info["core"].items() if c in entry["verdicts"] and r["candidate"]
        }
        assert set(sim_c) == set(day_c), (day, sorted(sim_c), sorted(day_c))
        for c, cand in sim_c.items():
            for k in ("direction", "lots", "bucket", "mult", "reason"):
                assert cand[k] == day_c[c][k], (day, c, k)
            for k in ("close", "r20", "r60", "atr", "entry", "stop", "target"):
                assert _close(cand[k], day_c[c][k]), (day, c, k, cand[k], day_c[c][k])
        n_cand += len(sim_c)
    assert n_cmp > 100
    print(f"compared {n_cmp} code-days, {n_cand} candidates, {n_blocked} blocked")


def test_report_rows_match_core(world):
    """The rows the daily report publishes carry the same numbers (display rounding only)."""
    day = _days(world)[-1]
    sigs, info, bars, entry = _daily(world, day)
    for s in sigs:
        res = info["core"].get(s["code"])
        if res is None or res["status"] in ("no_atr", "no_ret"):
            continue
        if res["r20"] is not None:
            assert abs(s["r20"] - res["r20"]) <= 5e-4 + 1e-12
            assert abs(s["r60"] - res["r60"]) <= 5e-4 + 1e-12
        if res["atr"] is not None:
            assert abs(s["atr"] - res["atr"]) <= 5e-3 + 1e-12
        if res["sizing"] is not None and res["status"] in ("ok", "lots0", "no_signal"):
            assert _close(s["stop_dist"], res["sizing"]["stop_dist"])
        assert s["signal_path"] == "signal_core"


def test_selected_after_caps_equal_with_held_book(world):
    import daily_update as du

    meta = {c: s["meta"] for c, s in world["series"].items()}
    n_sel = n_held_days = 0
    for day in _days(world):
        sigs, info, bars, entry = _daily(world, day)
        held = {
            c: {
                "lots": h["lots"],
                "direction": h["direction"],
                "bucket": h["bucket"],
                "entry": h["entry"],
                "atr": h["atr"],
                "mult": meta[c]["mult"],
            }
            for c, h in entry["held"].items()
        }
        # only the codes the backtest evaluated today are candidates there (held ones are not)
        rows = [s for s in sigs if s["code"] in entry["verdicts"] or s["code"] in held]
        du._apply_caps(rows, sizing_equity=entry["sizing_eq"], held=held)
        got = sorted((s["code"], int(s["lots_l1"])) for s in rows if s.get("selected"))
        want = sorted(entry["selected"])
        assert got == want, (day, got, want, sorted(held))
        n_sel += len(want)
        n_held_days += bool(held)
    print(f"selected matches on {N_DAYS} days ({n_sel} picks, {n_held_days} days with an open book)")


def test_observe_min_lots_only_touches_observe_sleeve(world):
    """The observe-sleeve floor is a daily-only sizing rule (the replay config has min_lots=0)."""
    day = _days(world)[-1]
    base, info0, _b, _e = _daily(world, day, observe_min_lots=0)
    flo, info1, _b2, _e2 = _daily(world, day, observe_min_lots=3)
    by0 = {s["code"]: s for s in base}
    for s in flo:
        o = by0[s["code"]]
        assert s["direction"] == o["direction"] and s.get("block") == o.get("block")
        if s.get("sleeve") != "observe":
            assert s["lots_raw"] == o["lots_raw"]
        elif s["lots_raw"] != o["lots_raw"]:
            assert s["min_lots_bumped"] and s["lots_raw"] == 3
            assert 0 < s["atr"] < s["close"] * 0.25


def test_empty_contract_cache_falls_back_not_crashes(world):
    day = _days(world)[-1]
    sigs, info, bars, entry = _daily(world, day)
    flagged = [s["code"] for s in sigs if s.get("adj_fallback")]
    if world["variant"] == "empty_cache":  # nothing cached -> raw-series fallback for everything
        assert flagged, "empty contract cache must surface adj_fallback"
        for s in sigs:
            if s.get("adj_fallback"):
                assert "换月价差" in (s.get("adj_note") or "")
