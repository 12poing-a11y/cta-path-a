# -*- coding: utf-8 -*-
"""R6c: roll-free signal series (adjusted.py) + audit gap-through-target exemption."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import historical_backtest as hb  # noqa: E402
from research.data_quality import adjusted as adj_mod  # noqa: E402
from research.data_quality import main_map as mm  # noqa: E402
from research.data_quality import rolls  # noqa: E402
from research.data_quality.adjusted import build_adjusted_series  # noqa: E402
from research.data_quality.main_map import MainMap, build_main_map  # noqa: E402

SPREAD = 10.0


def _days(n):
    out, k = [], 0
    import datetime as _dt

    d = _dt.date(2026, 1, 5)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += _dt.timedelta(days=1)
        k += 1
    return out


def _world(n=120, roll_at=(50, 90), spread=SPREAD):
    """Continuous series that hops to a new contract (+spread) at each roll index.

    Own-contract price of segment s on day j:  100 + 0.1*j + spread*s  (the new contract
    already trades the day before the roll at its own level, i.e. 110 when old = 100)."""
    days = _days(n)
    seg = [sum(1 for r in roll_at if j >= r) for j in range(n)]
    own = lambda s, j: 100.0 + 0.1 * j + spread * s  # noqa: E731
    cont = []
    for j, d in enumerate(days):
        c = own(seg[j], j)
        cont.append({"date": d, "open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "contract": f"X{seg[j]}"})
    store: dict[str, dict[str, dict]] = {}
    for s in range(len(roll_at) + 1):
        rows = {}
        for j, d in enumerate(days):
            c = own(s, j)
            rows[d] = {"date": d, "open": c, "high": c + 0.5, "low": c - 0.5, "close": c}
        store[f"X{s}"] = rows
    maps = {days[j]: f"X{seg[j]}" for j in range(n)}
    return days, cont, store, maps, own, seg


def _patch(monkeypatch, store):
    monkeypatch.setattr(mm, "cached_contracts_for", lambda code, root=None: sorted(store))
    monkeypatch.setattr(mm, "contract_bars_by_date", lambda c, root=None: store.get(c, {}))
    monkeypatch.setattr(rolls, "contract_bars_by_date", lambda c, root=None: store.get(c, {}))


def _series(cont, maps, code="X"):
    m = MainMap(maps={code: dict(maps)})
    return build_adjusted_series(code, cont, m)


def _true_rets(days, own, seg):
    """Own-contract 1-day returns (roll day: new contract vs ITS OWN previous close)."""
    out = [None]
    for j in range(1, len(days)):
        out.append(own(seg[j], j) / own(seg[j], j - 1) - 1.0)
    return out


def test_r20_does_not_jump_across_the_roll_day(monkeypatch):
    days, cont, store, maps, own, seg = _world()
    _patch(monkeypatch, store)
    a = _series(cont, maps)
    raw = [hb.ret_n(cont, i, 20) for i in range(len(cont))]
    adj = [a.ret_n(i, 20) for i in range(len(cont))]
    # raw r20 jumps by ~+9 points on the roll day (spread booked as return)
    assert raw[50] - raw[49] > 8.0
    # adjusted r20 moves like an ordinary day
    assert abs(adj[50] - adj[49]) < 0.5
    assert abs(adj[51] - adj[50]) < 0.5
    # equals the product of own-contract returns
    tr = _true_rets(days, own, seg)
    for i in (55, 60, 75):
        acc = 1.0
        for j in range(i - 19, i + 1):
            acc *= 1.0 + tr[j]
        assert adj[i] == pytest.approx((acc - 1.0) * 100.0, abs=1e-9)
    # windows that cross no roll are bit-identical to the raw series
    assert adj[30] == raw[30] and adj[70] == raw[70]


def test_roll_day_true_range_excludes_the_spread(monkeypatch):
    days, cont, store, maps, own, seg = _world()
    _patch(monkeypatch, store)
    a = _series(cont, maps)
    # raw TR on the roll day carries the 10-point spread; same-contract TR does not
    raw_tr = max(
        cont[50]["high"] - cont[50]["low"],
        abs(cont[50]["high"] - cont[49]["close"]),
        abs(cont[50]["low"] - cont[49]["close"]),
    )
    assert raw_tr > SPREAD
    assert a.roll[50] and not a.fallback[50]
    assert a.tr[50] == pytest.approx(1.0, abs=1e-9)  # H-L = 1; |H-C*| = 0.6
    assert a.tr[51] == pytest.approx(1.0, abs=1e-9)
    raw_atr = hb.atr14(cont, 55)
    assert raw_atr > 0.5 * SPREAD / 14.0 + 1.0 - 1e-9
    assert a.atr14(55) == pytest.approx(1.0, abs=1e-9)
    # windows without a roll are exactly the raw ATR
    assert a.atr14(30) == hb.atr14(cont, 30)


def test_signals_use_only_data_up_to_t(monkeypatch):
    days, cont, store, maps, own, seg = _world()
    _patch(monkeypatch, store)
    full_main = build_main_map({"X": {"meta": {"tick": 1.0}, "hist": cont}}, root=ROOT)
    full = build_adjusted_series("X", cont, full_main)
    full_vol = full.vol_hist()
    for T in (52, 70, 95, 110):
        cut = cont[: T + 1]
        cut_main = build_main_map({"X": {"meta": {"tick": 1.0}, "hist": cut}}, root=ROOT)
        part = build_adjusted_series("X", cut, cut_main)
        pv = part.vol_hist()
        for i in range(len(cut)):
            assert full_main.main("X", days[i]) == cut_main.main("X", days[i])
            assert part.ret_n(i, 20) == full.ret_n(i, 20)
            assert part.ret_n(i, 60) == full.ret_n(i, 60)
            assert part.atr14(i) == full.atr14(i)
            assert pv[i]["close"] == full_vol[i]["close"]
    # vol_bypass input: roll-free index ratios == roll-free returns (no 10-point jump)
    jump = full_vol[50]["close"] / full_vol[49]["close"] - 1.0
    assert abs(jump) < 0.01


def test_missing_price_falls_back_to_raw_and_is_counted(monkeypatch):
    days, cont, store, maps, own, seg = _world()
    # new contract has no bar on the day before the roll → cannot compute its return
    store["X1"] = {d: b for d, b in store["X1"].items() if d != days[49]}
    _patch(monkeypatch, store)
    a = _series(cont, maps)
    assert a.roll[50] and a.fallback[50]
    assert a.ret[50] == pytest.approx(cont[50]["close"] / cont[49]["close"] - 1.0)  # raw
    assert a.fallback_days() == 1
    # main_map unknown on a day → raw definition + counted as well
    maps2 = dict(maps)
    maps2[days[30]] = None
    a2 = _series(cont, maps2)
    assert a2.fallback[30] and a2.fallback[31]  # d and d+1 both lack a known (main_d, main_{d-1})
    assert a2.fallback_days() == 3  # the unpriced roll day (50) + the two days around the unknown main
    # window crossing a fallback day still returns a number
    assert a.ret_n(55, 20) is not None


def test_adjusted_pack_counts_rolls_and_no_fallback_when_priced(monkeypatch):
    days, cont, store, maps, own, seg = _world()
    _patch(monkeypatch, store)
    from research.data_quality.adjusted import build_adjusted_pack

    mp = MainMap(maps={"X": dict(maps)})
    pack = build_adjusted_pack({"X": {"hist": cont}}, mp)
    assert pack["X"].fallback_days() == 0
    assert pack["X"].roll_days() == 2


# ───────────────────────── audit exemption ─────────────────────────


def _audit(tmp_path, trade):
    from scripts.audit_exit_vs_daily import audit_bt

    days = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]
    cdir = tmp_path / ".cache" / "contracts"
    cdir.mkdir(parents=True, exist_ok=True)
    old = [
        {"date": d, "open": 1000 + i, "high": 1008 + i, "low": 992 + i, "close": 1000 + i}
        for i, d in enumerate(days)
    ]
    (cdir / "AA2505.json").write_text(json.dumps({"bars": old}), encoding="utf-8")
    snap = {"bars": {"AA": [dict(b) for b in old]}}
    t = {
        "code": "AA",
        "direction": "多",
        "lots": 1,
        "entry_date": "2026-03-02",
        "date": "2026-03-05",
        "fill_price_basis": "continuous_proxy",
        "held_contract": "AA2505",
    }
    t.update(trade)
    return audit_bt({"closed_pnls": [t]}, root=tmp_path, snap=snap, tick_by_code={"AA": 1.0})


def test_audit_exempts_long_target_when_open_gapped_through(tmp_path):
    # day 03-05 bar: O 1003 H 1011 L 995 C 1003; target 990 lies below the low
    rep = _audit(tmp_path, {"reason": "target", "target": 990.0, "stop": 970.0, "exit": 990.0})
    assert rep["mismatches"] == 0
    assert rep["gap_through_target_conservative"] == 1


def test_audit_exempts_short_target_when_open_gapped_through(tmp_path):
    rep = _audit(
        tmp_path,
        {"direction": "空", "reason": "target", "target": 1020.0, "stop": 1040.0, "exit": 1020.0},
    )
    assert rep["mismatches"] == 0
    assert rep["gap_through_target_conservative"] == 1


def test_audit_does_not_exempt_stop_with_same_gap(tmp_path):
    # short, opened above its stop (1003 >= 990), filled at the stop price below the low
    rep = _audit(
        tmp_path,
        {"direction": "空", "reason": "stop", "stop": 990.0, "target": 900.0, "exit": 990.0},
    )
    assert rep["gap_through_target_conservative"] == 0
    assert rep["mismatches"] == 1
    assert "exit_outside_held_bar_range" in rep["mismatch_trades"][0]["problems"]


def test_audit_does_not_exempt_target_filled_away_from_target_or_without_gap(tmp_path):
    # filled 5 points away from the target → not the convention
    rep = _audit(tmp_path, {"reason": "target", "target": 990.0, "stop": 970.0, "exit": 985.0})
    assert rep["gap_through_target_conservative"] == 0 and rep["mismatches"] == 1
    # open did NOT cross the target (target above open) yet the price is outside the range
    rep = _audit(tmp_path, {"reason": "target", "target": 1050.0, "stop": 970.0, "exit": 1050.0})
    assert rep["gap_through_target_conservative"] == 0 and rep["mismatches"] >= 1
