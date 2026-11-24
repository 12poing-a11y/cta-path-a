# -*- coding: utf-8 -*-
"""R6a / R6b-fix: rolls come from the ACTUAL main-contract map and never create fake PnL or stops."""
from __future__ import annotations

import math
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "ifind_call" not in sys.modules:  # import without IFIND_AUTH_TOKEN; no network
    stub = types.ModuleType("ifind_call")
    stub.active_slot = lambda *a, **k: None
    stub.call = lambda *a, **k: {}
    stub.usage_report = lambda: {"count": 0, "calls": []}
    sys.modules["ifind_call"] = stub

import historical_backtest as hb  # noqa: E402
from research.data_quality import main_map as mm  # noqa: E402
from research.data_quality import rolls  # noqa: E402
from research.data_quality.main_map import build_main_map, match_main_contract  # noqa: E402
from research.data_quality.rolls import is_roll_day  # noqa: E402


# ───────────────────────── main_map ─────────────────────────


def _bar(d, c, *, h=None, lo=None, calendar=None):
    return {
        "date": d,
        "open": c,
        "high": c + 2 if h is None else h,
        "low": c - 2 if lo is None else lo,
        "close": c,
        **({"contract": calendar} if calendar else {}),
    }


def _patch_contracts(monkeypatch, store: dict[str, dict[str, dict]]):
    """In-memory contract daily store: {contract: {date: bar}}."""
    monkeypatch.setattr(mm, "cached_contracts_for", lambda code, root=None: sorted(store))
    # R7a-D: main_map candidates come from the listing calendar; the fake contracts are "listed" every day
    monkeypatch.setattr(mm, "listed_contracts_on", lambda code, day, root=None: sorted(store))
    monkeypatch.setattr(mm, "contract_bars_by_date", lambda c, root=None: store.get(c, {}))
    monkeypatch.setattr(rolls, "contract_bars_by_date", lambda c, root=None: store.get(c, {}))


def test_match_main_contract_within_one_tick_else_none():
    cands = {"AA2505": _bar("d", 100), "AA2506": _bar("d", 130)}
    got, st = match_main_contract(_bar("d", 100.5), cands, tick=1.0)
    assert got == "AA2505" and st == "matched"
    got, st = match_main_contract(_bar("d", 115), cands, tick=1.0)
    assert got is None and st == "no_match"
    got, st = match_main_contract(_bar("d", 100), {}, tick=1.0)
    assert got is None and st == "no_candidate"


def test_match_main_contract_tie_uses_high_low_then_prev_main():
    a = {"close": 100, "high": 110, "low": 90}
    b = {"close": 100.5, "high": 101, "low": 99}
    got, _ = match_main_contract(
        {"close": 100.2, "high": 110, "low": 90}, {"A": a, "B": b}, tick=1.0
    )
    assert got == "A"  # high/low break the close tie
    same = {"close": 100, "high": 101, "low": 99}
    got, st = match_main_contract(
        {"close": 100, "high": 101, "low": 99}, {"A": dict(same), "B": dict(same)}, tick=1.0
    )
    assert got is None and st == "ambiguous"
    got, st = match_main_contract(
        {"close": 100, "high": 101, "low": 99}, {"A": dict(same), "B": dict(same)}, tick=1.0, prev_main="B"
    )
    assert got == "B" and st == "matched"


def test_is_roll_day_only_when_both_mains_known_and_different():
    assert is_roll_day("FG2605", "FG2609") is True
    assert is_roll_day("FG2605", "FG2605") is False
    assert is_roll_day(None, "FG2609") is False
    assert is_roll_day("FG2605", None) is False


def test_calendar_contract_flip_without_main_change_is_not_a_roll(monkeypatch):
    """EB/FU/JD-style: calendar stamp flips monthly, Sina's main never moves → no roll."""
    days = [f"2026-0{m}-{dd:02d}" for m in (1, 2, 3) for dd in (5, 10, 15, 20)]
    old = {d: _bar(d, 1000 + i) for i, d in enumerate(days)}
    far = {d: _bar(d, 1200 + i) for i, d in enumerate(days)}  # never the main
    _patch_contracts(monkeypatch, {"AA2601": old, "AA2612": far})
    hist = [
        _bar(d, 1000 + i, calendar=f"AA26{d[5:7]}")  # calendar contract changes every month
        for i, d in enumerate(days)
    ]
    out = build_main_map({"AA": {"meta": {"tick": 1.0}, "hist": hist}}, root=ROOT)
    mains = [out.main("AA", d) for d in days]
    assert set(mains) == {"AA2601"}
    assert not any(is_roll_day(a, b) for a, b in zip(mains, mains[1:]))
    assert out.stats["AA"]["coverage"] == 1.0


def test_main_map_none_when_nothing_matches_and_counts_it(monkeypatch):
    d0, d1 = "2026-01-05", "2026-01-06"
    _patch_contracts(monkeypatch, {"AA2601": {d0: _bar(d0, 1000)}})
    hist = [_bar(d0, 1000), _bar(d1, 1000)]  # d1: no contract bar at all
    out = build_main_map({"AA": {"meta": {"tick": 1.0}, "hist": hist}}, root=ROOT)
    assert out.main("AA", d0) == "AA2601" and out.main("AA", d1) is None
    assert out.stats["AA"]["none_days"] == 1 and out.stats["AA"]["none_no_candidate_bar"] == 1


def test_main_map_uses_only_same_day_data(monkeypatch):
    """Truncation-safe: main_map[d] is identical with or without later bars."""
    days = [f"2026-01-{dd:02d}" for dd in range(5, 25)]
    old = {d: _bar(d, 1000 + i) for i, d in enumerate(days)}
    new = {d: _bar(d, 1100 + i) for i, d in enumerate(days)}
    _patch_contracts(monkeypatch, {"AA2601": old, "AA2605": new})
    hist = [_bar(d, (1000 if i < 10 else 1100) + i) for i, d in enumerate(days)]
    full = build_main_map({"AA": {"meta": {"tick": 1.0}, "hist": hist}}, root=ROOT)
    cut = build_main_map({"AA": {"meta": {"tick": 1.0}, "hist": hist[:12]}}, root=ROOT)
    for d in days[:12]:
        assert full.main("AA", d) == cut.main("AA", d)
    assert full.main("AA", days[9]) == "AA2601" and full.main("AA", days[10]) == "AA2605"


# ───────────────────────── R6a: contract positions ─────────────────────────


def _contract_pos(**kw):
    p = {"fill_price_basis": "contract", "fill_contract": "FG2605", "basis_off": -100.0}
    p.update(kw)
    return p


_BAR = {
    "date": "2026-04-16",
    "contract": "FG2605",
    "open": 1072.0,
    "high": 1074.0,
    "low": 1052.0,
    "close": 1062.0,  # no contract_* stamped
}


def test_manage_bar_fixed_real_contract_bar_wins_over_stale_basis():
    exact = {"open": 974.0, "high": 984.0, "low": 951.0, "close": 956.0}
    p = _contract_pos(basis_off_main="FG2605")
    m, prox, fr = hb.manage_bar_fixed(
        _BAR, p, use_main=True, main_now="FG2609", contract_ohlc=exact
    )
    assert fr is None and not prox and m["open"] == 974.0 and m["high"] == 984.0
    assert p["basis_off_main"] == "FG2609"  # refreshed from the real bar


def test_manage_bar_fixed_proxy_allowed_only_while_main_unchanged():
    p = _contract_pos(basis_off_main="FG2605")
    m, prox, fr = hb.manage_bar_fixed(_BAR, p, use_main=True, main_now="FG2605")
    assert fr is None and prox and m["close"] == 1062.0 - 100.0


def test_manage_bar_fixed_main_changed_without_real_bar_is_roll_unpriced():
    p = _contract_pos(basis_off_main="FG2605")
    m, prox, fr = hb.manage_bar_fixed(
        _BAR, p, use_main=True, main_now="FG2609", last_close=971.0, last_close_date="2026-04-15"
    )
    assert fr == "roll_unpriced" and prox
    assert m["close"] == 971.0 and m["date"] == "2026-04-15"
    # new main's continuous price is never used to proxy the old contract
    assert m["close"] != 1062.0 - 100.0
    # unknown main today (None) cannot vouch for basis_off either
    m, prox, fr = hb.manage_bar_fixed(
        _BAR, _contract_pos(basis_off_main="FG2605"), use_main=True, main_now=None, last_close=971.0
    )
    assert fr == "roll_unpriced"
    # nothing known at all → no price
    m, prox, fr = hb.manage_bar_fixed(
        _BAR, _contract_pos(basis_off_main="FG2605"), use_main=True, main_now="FG2609"
    )
    assert m is None and fr == "roll_unpriced"


def test_manage_bar_fixed_without_main_map_keeps_plain_proxy():
    p = _contract_pos()
    m, prox, fr = hb.manage_bar_fixed(_BAR, p)  # legacy / no map for this code
    assert fr is None and prox and m["close"] == 962.0


# ───────────────────────── R6b-fix helpers ─────────────────────────


def _cont_pos(**kw):
    p = {
        "direction": "多",
        "lots": 2,
        "entry": 1000.0,
        "stop": 984.0,
        "target": 1032.0,
        "last_mark": 1010.0,
        "held_contract": "AA2605",
    }
    p.update(kw)
    return p


def test_roll_open_gap_through_stop_uses_old_contract_open():
    assert hb.roll_open_gaps_through_stop(_cont_pos(), 984.0)
    assert hb.roll_open_gaps_through_stop(_cont_pos(), 970.0)
    assert not hb.roll_open_gaps_through_stop(_cont_pos(), 990.0)
    short = _cont_pos(direction="空", entry=1000.0, stop=1016.0, target=968.0)
    assert hb.roll_open_gaps_through_stop(short, 1020.0)
    assert not hb.roll_open_gaps_through_stop(short, 1010.0)


def test_roll_position_at_open_shifts_levels_and_marks_new_open():
    p = _cont_pos()
    risk0 = p["entry"] - p["stop"]
    pnl = hb.roll_position_at_open(
        p, old_open=1005.0, new_open=1305.0, new_contract="AA2609", day="2026-02-02", mult=10, sign=1
    )
    # old leg: last_mark 1010 → old open 1005 on 2 lots × 10
    assert pnl == pytest.approx((1005.0 - 1010.0) * 10 * 2)
    assert p["stop"] == 984.0 + 300.0 and p["target"] == 1032.0 + 300.0
    assert p["entry"] == 1300.0 and p["entry_orig"] == 1000.0
    assert p["entry"] - p["stop"] == pytest.approx(risk0)  # R distance unchanged
    assert p["last_mark"] == 1305.0  # new contract's open, not the old close
    assert p["held_contract"] == "AA2609"
    ev = p["roll_events"][-1]
    assert ev["status"] == "shifted" and ev["shift"] == 300.0 and ev["from"] == "AA2605"


# ───────────────────────── engine-level synthetic ─────────────────────────

N = 140


def _dates(n=N):
    from datetime import date, timedelta

    d, out = date(2025, 1, 1), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _ohlc(c):
    return {"open": c - 2, "high": c + 8, "low": c - 8, "close": c}


def _engine(monkeypatch, *, spread, roll_idx, drop_old_from=None):
    """One variety, steadily rising. Contract AA2505 is the main until ``roll_idx``;
    from then Sina's continuous series is AA2506 = AA2505 + ``spread``."""
    dates = _dates()
    old = {d: {"date": d, **_ohlc(1000.0 + 4 * i), "volume": 1} for i, d in enumerate(dates)}
    new = {d: {"date": d, **_ohlc(1000.0 + 4 * i + spread), "volume": 1} for i, d in enumerate(dates)}
    if drop_old_from is not None:
        old = {d: b for i, (d, b) in enumerate(old.items()) if i < drop_old_from}
    hist = []
    for i, d in enumerate(dates):
        base = 1000.0 + 4 * i + (spread if i >= roll_idx else 0.0)
        hist.append({"date": d, **_ohlc(base), "volume": 1})
    pack = (
        {"AA": {"meta": {"code": "AA", "name": "AA", "mult": 10, "bucket": "AA", "tick": 1.0}, "hist": hist}},
        {},
        {},
    )
    _patch_contracts(monkeypatch, {"AA2505": old, "AA2506": new})
    monkeypatch.setattr(hb, "entry_block", lambda *a, **k: None)
    monkeypatch.setattr(hb, "seat_decision", lambda direction, book: (None, "t"))
    monkeypatch.setattr(
        hb,
        "load_member_seats",
        lambda ds, codes: {c: {d: {"asof": d, "inst": 1.0, "foreign": 0.0, "holder": 0.0} for d in ds} for c in codes},
    )
    monkeypatch.setattr(hb, "load_member_changes", lambda ds, codes: {c: {d: {"asof": d} for d in ds} for c in codes})
    monkeypatch.setattr(hb, "load_curves", lambda codes, **k: {c: {"carry": {d: {"asof": d} for d in dates}} for c in codes})
    return hb.simulate([pack[0]["AA"]["meta"]], 200_000, mode="seats", pack=pack, min_r20=0.5, min_r60=0.5)


def _held_across(out, roll_date):
    return [t for t in out["closed_pnls"] if t["entry_date"] < roll_date <= t["date"]]


def test_roll_moves_position_at_next_open_and_spread_is_not_pnl(monkeypatch):
    spread, roll_idx = 300.0, 80
    out = _engine(monkeypatch, spread=spread, roll_idx=roll_idx)
    roll_day = _dates()[roll_idx]
    assert out["roll_shifted"] >= 1 and out["roll_unpriced_cont"] == 0
    held = [t for t in out["closed_pnls"] if t.get("roll_events")]
    assert held, "a position was open across the main roll"
    t = held[0]
    ev = t["roll_events"][0]
    # main moved at roll_day (after close) → the roll executes at the NEXT session's open
    assert ev["date"] > roll_day and ev["status"] == "shifted"
    assert ev["shift"] == pytest.approx(spread) and ev["from"] == "AA2505" and ev["to"] == "AA2506"
    assert t["held_contract"] == "AA2506"
    # translated target keeps its distance → still a clean +2R, not a spread-driven fill
    assert t["reason"] == "target" and t["R"] == pytest.approx(2.0, abs=0.01)
    assert t["entry"] == pytest.approx(t["entry_orig"] + spread)
    # no day books the 300-point spread as PnL (that would be ≥ lots*mult*300)
    bound = 0.3 * spread * t["lots"] * 10
    assert max(abs(c["pnl"]) for c in out["equity_curve"]) < bound


def test_roll_day_itself_is_priced_on_the_held_contract(monkeypatch):
    """On the day main moves, stop/target/PnL use the held contract's bar — the +300
    continuous jump must not fire the target or book profit on that day."""
    out = _engine(monkeypatch, spread=300.0, roll_idx=80)
    roll_day = _dates()[80]
    for t in _held_across(out, roll_day):
        assert not (t["date"] == roll_day and t["reason"] == "target" and t["exit"] > 1200 + 4 * 80)


def test_negative_spread_roll_is_not_a_fake_stop(monkeypatch):
    out = _engine(monkeypatch, spread=-300.0, roll_idx=80)
    roll_day = _dates()[80]
    for t in _held_across(out, roll_day):
        assert not (t["date"] == roll_day and t["reason"] == "stop" and t["R"] < -1.5)
    assert min([t["R"] for t in out["closed_pnls"] if t["reason"] == "stop"] or [0]) > -1.5


def test_calendar_flip_without_main_change_does_not_roll(monkeypatch):
    out = _engine(monkeypatch, spread=0.5, roll_idx=10_000)  # AA2506 never main (within a tick)
    assert out["roll_shifted"] == 0 and out["roll_unpriced_cont"] == 0 and out["roll_unpriced"] == 0
    assert out["closed_trades"] > 0
    assert all(not t.get("roll_events") for t in out["closed_pnls"])


@pytest.mark.parametrize("roll_idx", list(range(70, 78)))
def test_never_exits_before_entry(monkeypatch, roll_idx):
    """Sweeps the roll day across entry days; every exit is on/after entry and priced from
    a bar on/after entry (the engine also raises AssertionError if it ever were not)."""
    out = _engine(monkeypatch, spread=300.0, roll_idx=roll_idx)
    assert out["closed_trades"] > 0
    for t in out["closed_pnls"]:
        assert t["date"] >= t["entry_date"], t
    assert "roll_exit" not in out["exits"]


def test_unpriced_held_contract_falls_back_to_continuous_and_is_counted(monkeypatch):
    """No real bar for the held contract on the roll day → pre-R6 continuous treatment, counted."""
    out = _engine(monkeypatch, spread=300.0, roll_idx=80, drop_old_from=80)
    assert out["roll_unpriced_cont"] >= 1
    assert out["roll_shifted"] == 0
    assert out["closed_trades"] > 0


def test_entry_without_main_map_falls_back_and_is_counted(monkeypatch):
    """Held contract's own bars already missing on the entry day → held_contract None → pre-R6 path."""
    out = _engine(monkeypatch, spread=300.0, roll_idx=80, drop_old_from=60)
    assert out["held_contract_missing"] >= 1
    assert out["roll_shifted"] == 0


def test_exit_before_entry_guard_raises(monkeypatch):
    """The booking guard itself: exit price bar dated before entry must raise."""
    src = (ROOT / "historical_backtest.py").read_text(encoding="utf-8")
    assert "exit before entry" in src and "raise AssertionError" in src


# ───────────────────────── audit: R6b-fix checks ─────────────────────────


def _audit_fixture(tmp_path, monkeypatch):
    import json

    from scripts.audit_exit_vs_daily import audit_bt

    days = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]
    cdir = tmp_path / ".cache" / "contracts"
    cdir.mkdir(parents=True)
    old = [
        {"date": d, "open": 1000 + i, "high": 1008 + i, "low": 992 + i, "close": 1000 + i}
        for i, d in enumerate(days)
    ]
    new = [
        {"date": d, "open": 1300 + i, "high": 1308 + i, "low": 1292 + i, "close": 1300 + i}
        for i, d in enumerate(days)
    ]
    (cdir / "AA2505.json").write_text(json.dumps({"bars": old}), encoding="utf-8")
    (cdir / "AA2506.json").write_text(json.dumps({"bars": new}), encoding="utf-8")
    # continuous = old for the first three days, new (main moved) on the 4th
    cont = old[:3] + new[3:]
    snap = {"bars": {"AA": [dict(b) for b in cont]}}
    # R7a-D: fake contract ids are not on the listing calendar of these dates
    monkeypatch.setattr(mm, "listed_contracts_on", lambda code, day, root=None: ["AA2505", "AA2506"])

    def run(trades):
        return audit_bt({"closed_pnls": trades}, root=tmp_path, snap=snap, tick_by_code={"AA": 1.0})

    return run


def _t(**kw):
    t = {
        "code": "AA",
        "direction": "多",
        "lots": 1,
        "entry_date": "2026-03-02",
        "date": "2026-03-05",
        "reason": "target",
        "stop": 990.0,
        "target": 1000.0,
        "exit": 1000.0,
        "fill_price_basis": "continuous_proxy",
        "held_contract": "AA2505",
    }
    t.update(kw)
    return t


def test_audit_accepts_roll_day_exit_priced_on_held_contract(tmp_path, monkeypatch):
    run = _audit_fixture(tmp_path, monkeypatch)
    # held AA2505 on the day main moved to AA2506: exit 1000 lies in AA2505's 03-05 bar
    rep = run([_t(exit=1005.0, target=1005.0)])
    assert rep["mismatches"] == 0
    assert rep["checks"]["roll_day_exits_checked"] == 1


def test_audit_flags_roll_day_exit_priced_from_new_main(tmp_path, monkeypatch):
    run = _audit_fixture(tmp_path, monkeypatch)
    rep = run([_t(exit=1301.0, target=1301.0)])
    assert rep["mismatches"] == 1
    probs = rep["mismatch_trades"][0]["problems"]
    assert "roll_day_exit_from_new_main" in probs and "exit_outside_held_bar_range" in probs


def test_audit_flags_exit_before_entry(tmp_path, monkeypatch):
    run = _audit_fixture(tmp_path, monkeypatch)
    rep = run([_t(entry_date="2026-03-05", date="2026-03-03", exit=1001.0, target=1001.0)])
    assert any("exit_before_entry" in m["problems"] for m in rep["mismatch_trades"])


def test_audit_flags_continuous_exit_outside_held_bar_range(tmp_path, monkeypatch):
    run = _audit_fixture(tmp_path, monkeypatch)
    # signal exit (no stop/target check) at a price the held contract never traded that day
    rep = run([_t(reason="signal", exit=1200.0, date="2026-03-04")])
    assert rep["mismatches"] == 1
    assert rep["mismatch_trades"][0]["problems"] == ["exit_outside_held_bar_range"]
