# -*- coding: utf-8 -*-
"""R8b: --equity / --filter-unit-risk / --filter-atr-spike are research-only (need --out); the two entry filters
fire / do not fire on constructed data and never read bars dated after the signal day."""
from __future__ import annotations

import math
import sys
import types
from datetime import date, timedelta

import pytest

if "ifind_call" not in sys.modules:  # import without IFIND_AUTH_TOKEN; no network
    _stub = types.ModuleType("ifind_call")
    _stub.active_slot = lambda *a, **k: None
    _stub.call = lambda *a, **k: {}
    _stub.usage_report = lambda: {"count": 0, "calls": []}
    sys.modules["ifind_call"] = _stub

import historical_backtest as hb  # noqa: E402
from research.data_quality.adjusted import build_adjusted_series  # noqa: E402
from research.execution import entry_filters as ef  # noqa: E402


# --------------------------------------------------------------------------------------------- CLI gate
class _Reached(Exception):
    """Raised by the stub replacing the data fetch: we got past all R8 guards."""


def _run_main(monkeypatch, capsys, argv, *, fetch="forbid"):
    monkeypatch.setattr(sys, "argv", ["historical_backtest.py", *argv])

    def _stub(*a, **k):
        if fetch == "forbid":
            raise AssertionError("main() must refuse before fetching any data")
        raise _Reached()

    monkeypatch.setattr(hb, "_fetch_pack", _stub)
    rc = hb.main()
    return rc, capsys.readouterr()


@pytest.mark.parametrize(
    "argv",
    [["--equity", "300000"], ["--equity=500000"], ["--filter-unit-risk"], ["--filter-atr-spike"],
     ["--fill", "next_open", "--equity", "1000000", "--filter-unit-risk", "--filter-atr-spike"]],
)
def test_overrides_without_out_are_refused(monkeypatch, capsys, argv):
    rc, cap = _run_main(monkeypatch, capsys, argv)
    assert rc == 2
    assert "--out" in cap.err


@pytest.mark.parametrize(
    "extra, needle",
    [(["--equity"], "needs a value"), (["--equity", "0"], "must be"), (["--equity", "abc"], "bad value"),
     (["--equity", "-5"], "must be")],
)
def test_bad_equity_is_refused_even_with_out(monkeypatch, capsys, tmp_path, extra, needle):
    out = tmp_path / "x" / "r.json"
    rc, cap = _run_main(monkeypatch, capsys, ["--out", str(out), *extra])
    assert rc == 2
    assert needle in cap.err
    assert not out.exists() and not out.parent.exists()


def test_overrides_not_allowed_with_other_modes(monkeypatch, capsys, tmp_path):
    for mode in ("--compare", "--rr-grid", "--roll-grid", "--hedge-grid", "--ctf"):
        rc, cap = _run_main(monkeypatch, capsys, ["--out", str(tmp_path / "r.json"), "--filter-atr-spike", mode])
        assert rc == 2, mode
        assert "default single run" in cap.err


def test_valid_overrides_reach_the_run_header_and_write_nothing(monkeypatch, capsys, tmp_path):
    out = tmp_path / "r8" / "r.json"
    monkeypatch.setattr(sys, "argv", ["historical_backtest.py", "--out", str(out), "--equity", "1000000",
                                     "--filter-unit-risk", "--filter-atr-spike"])
    monkeypatch.setattr(hb, "_fetch_pack", lambda *a, **k: (_ for _ in ()).throw(_Reached()))
    with pytest.raises(_Reached):
        hb.main()
    header = capsys.readouterr().out
    assert "equity0=1000000.0" in header
    assert "filter_unit_risk=True" in header and "filter_atr_spike=True" in header
    assert not out.exists()


def test_parser(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x", "--fill", "next_open", "--out", "a.json"])
    assert hb.r8_overrides_from_argv() == {}
    assert hb._r8_flags_present() is False
    monkeypatch.setattr(sys, "argv", ["x", "--out", "a.json", "--equity=1e6", "--filter-atr-spike"])
    assert hb.r8_overrides_from_argv() == {"equity0": 1_000_000.0, "filter_atr_spike": True}
    assert hb._r8_flags_present() is True


def test_out_alone_is_unchanged_r0_behaviour(monkeypatch, capsys, tmp_path):
    """--out without R8 flags must not trip the R8 guard."""
    monkeypatch.setattr(sys, "argv", ["historical_backtest.py", "--out", str(tmp_path / "r.json")])
    monkeypatch.setattr(hb, "_fetch_pack", lambda *a, **k: (_ for _ in ()).throw(_Reached()))
    with pytest.raises(_Reached):
        hb.main()
    assert "research overrides" not in capsys.readouterr().err


# --------------------------------------------------------------------------------------- pure functions
def test_unit_notional_exceeds_trigger_nontrigger_and_boundary():
    # cap amount = 200k x 50% = 100k ; half = 50k
    assert ef.gross_cap_amount(200_000, 50) == 100_000
    assert ef.unit_notional_exceeds(close=6000, mult=10, sizing_eq=200_000, max_gross_pct=50) is True   # 60k > 50k
    assert ef.unit_notional_exceeds(close=4000, mult=10, sizing_eq=200_000, max_gross_pct=50) is False  # 40k <= 50k
    assert ef.unit_notional_exceeds(close=5000, mult=10, sizing_eq=200_000, max_gross_pct=50) is False  # == half: allowed
    # the cap scales with equity: the same 60k lot is fine at 1,000,000
    assert ef.unit_notional_exceeds(close=6000, mult=10, sizing_eq=1_000_000, max_gross_pct=50) is False


def test_unit_risk_exceeds_trigger_nontrigger_and_boundary():
    assert ef.unit_risk_exceeds(risk_per_lot=5_001, day_risk=5_000) is True
    assert ef.unit_risk_exceeds(risk_per_lot=4_999, day_risk=5_000) is False
    assert ef.unit_risk_exceeds(risk_per_lot=5_000, day_risk=5_000) is False


def test_atr_spike_trigger_nontrigger_boundary_and_unavailable():
    assert ef.atr_spike(31.0, 20.0) is True      # 1.55
    assert ef.atr_spike(29.0, 20.0) is False     # 1.45
    assert ef.atr_spike(30.0, 20.0) is False     # exactly 1.5: strictly greater is required
    assert ef.atr_spike(30.0, None) is None      # ATR100 unavailable -> filter must not fire
    assert ef.atr_spike(None, 20.0) is None
    assert ef.atr_spike(30.0, 0.0) is None


def _bars(n, half=8.0, widen_from=None, widen_half=30.0, start=1000.0):
    d, dates = date(2025, 1, 1), []
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    out = []
    for i, ds in enumerate(dates):
        c = start * (1 + 0.004 * i) + 15 * math.sin(i / 3)
        h = widen_half if (widen_from is not None and i >= widen_from) else half
        out.append({"date": ds, "open": c - 2, "high": c + h, "low": c - h, "close": c, "volume": 1})
    return out


def test_atr_n_matches_atr14_and_needs_n_bars():
    hist = _bars(140, widen_from=110)
    adj = build_adjusted_series("AA", hist, None)  # no main map -> raw-continuous fallback on every day
    for i in (14, 15, 60, 99, 100, 139):
        assert adj.atr_n(i, 14) == adj.atr14(i)
    assert adj.atr_n(99, 100) is None            # only 99 bars precede index 99
    assert adj.atr_n(100, 100) is not None
    assert ef.long_atr(adj, hist, 99) is None and ef.long_atr(adj, hist, 100) == adj.atr_n(100, 100)
    # raw fallback (no adjusted series) agrees with the adjusted value when there is no roll
    assert ef.long_atr(None, hist, 130) == pytest.approx(adj.atr_n(130, 100))


def test_atr_spike_value_on_constructed_data_and_no_future_bars():
    hist = _bars(140, widen_from=100)            # TR jumps from ~16 to ~60 at index 100
    adj = build_adjusted_series("AA", hist, None)
    i = 120
    a14, a100 = adj.atr14(i), ef.long_atr(adj, hist, i)
    assert ef.atr_spike(a14, a100) is True and a14 / a100 > 1.5
    calm = build_adjusted_series("AA", _bars(140), None)
    assert ef.atr_spike(calm.atr14(120), ef.long_atr(calm, _bars(140), 120)) is False
    # truncation safety: values at i do not change if every later bar is cut or replaced by garbage
    cut = build_adjusted_series("AA", hist[: i + 1], None)
    garbage = [dict(b) for b in hist]
    for b in garbage[i + 1:]:
        b.update(high=b["high"] * 5, low=b["low"] / 5, close=b["close"] * 3)
    junk = build_adjusted_series("AA", garbage, None)
    for s in (cut, junk):
        assert s.atr14(i) == a14
        assert ef.long_atr(s, s.hist, i) == a100


# ------------------------------------------------------------------------------------------- engine level
def _pack(*, widen_from=None):
    series = {}
    for k, code in enumerate(("AA", "BB", "CC")):
        hist = _bars(140, widen_from=widen_from)
        for i, b in enumerate(hist):  # make the three symbols differ a little, same shape
            shift = 15 * math.sin(i / 3 + k) - 15 * math.sin(i / 3)
            for f in ("open", "high", "low", "close"):
                b[f] += shift
        series[code] = {"meta": {"code": code, "name": code, "mult": 10, "bucket": code}, "hist": hist}
    return series, {}, {}


def _simulate(monkeypatch, pack, equity0, **kw):
    dates = [b["date"] for b in pack[0]["AA"]["hist"]]

    def fake_block(m, hist, i, direction, d, code, a, curves, member, peers):
        return None

    def books(ds, codes):
        return {c: {d: {"asof": d, "inst": 1.0, "foreign": 0.0, "holder": 0.0} for d in ds} for c in codes}

    monkeypatch.setattr(hb, "entry_block", fake_block)
    monkeypatch.setattr(hb, "seat_decision", lambda direction, book: (None, "t"))
    monkeypatch.setattr(hb, "load_member_seats", books)
    monkeypatch.setattr(hb, "load_member_changes", lambda ds, codes: {c: {d: {"asof": d} for d in ds} for c in codes})
    monkeypatch.setattr(hb, "load_curves", lambda codes, **k: {c: {"carry": {d: {"asof": d} for d in dates}} for c in codes})
    log: list = []
    out = hb.simulate([v["meta"] for v in pack[0].values()], equity0, mode="base", pack=pack, min_r20=0.5,
                      min_r60=0.5, fill_price="next_open", candidate_log=log, **kw)
    return out, log


def _same_result(a, b):
    return a["closed_pnls"] == b["closed_pnls"] and a["equity_curve"] == b["equity_curve"]


def test_filters_off_keep_the_formal_key_set(monkeypatch):
    out, _ = _simulate(monkeypatch, _pack(), 200_000)
    assert "entry_filters" not in out


def test_f1_notional_filter_does_not_trigger_at_ample_equity(monkeypatch):
    off, _ = _simulate(monkeypatch, _pack(), 200_000)
    on, _ = _simulate(monkeypatch, _pack(), 200_000, filter_unit_risk=True)
    assert off["closed_pnls"], "constructed data must trade"
    assert on["entry_filters"]["hits"]["unit_notional"] == 0 and on["entry_filters"]["log"] == []
    assert on["entry_filters"]["hits"]["evaluated"] > 0
    assert _same_result(off, on)  # a filter that never fires changes nothing


def test_f1_notional_filter_triggers_at_small_equity(monkeypatch):
    # equity 30k: gross cap 15k, half 7.5k, 1-lot notional 12.4k..15.6k -> every candidate is filtered
    off, log_off = _simulate(monkeypatch, _pack(), 30_000)
    on, log_on = _simulate(monkeypatch, _pack(), 30_000, filter_unit_risk=True)
    assert off["closed_pnls"], "without the filter the early (1-lot <= cap) candidates trade"
    assert on["closed_pnls"] == []
    assert on["entry_filters"]["hits"]["unit_notional"] > 0
    assert any(e["cands"] for e in log_off) and not any(e["cands"] for e in log_on)  # filtered before the caps
    for r in on["entry_filters"]["log"]:
        assert r["reason"] == "unit_notional" and r["unit_notional"] > 0.5 * r["gross_cap_amount"]


def test_unit_risk_budget_half_is_inert_at_min_lots_zero_and_fires_with_min_lots(monkeypatch):
    base, _ = _simulate(monkeypatch, _pack(), 200_000)
    inert, _ = _simulate(monkeypatch, _pack(), 200_000, filter_unit_risk_budget=True)
    assert inert["entry_filters"]["hits"]["unit_risk"] == 0 and _same_result(base, inert)
    # min_lots=1 lifts 0-lot signals to 1 lot whose stop risk exceeds the budget -> the risk half must fire
    small = 3_000  # day_risk = 3,000 x 1.5% = 45 yuan < 1-lot stop risk (~180)
    lifted, _ = _simulate(monkeypatch, _pack(), small, min_lots=1)
    gated, _ = _simulate(monkeypatch, _pack(), small, min_lots=1, filter_unit_risk_budget=True)
    assert gated["entry_filters"]["hits"]["unit_risk"] > 0
    assert all(r["risk_per_lot"] > r["day_risk"] for r in gated["entry_filters"]["log"])
    assert gated["entry_filters"]["hits"]["unit_risk"] == gated["entry_filters"]["hits"]["evaluated"] > 0
    assert "entry_filters" not in lifted  # filters off -> formal key set


def test_f2_atr_spike_does_not_trigger_in_a_calm_market_and_is_inactive_before_atr100(monkeypatch):
    off, _ = _simulate(monkeypatch, _pack(), 2_000_000)
    on, _ = _simulate(monkeypatch, _pack(), 2_000_000, filter_atr_spike=True)
    assert off["closed_pnls"]
    h = on["entry_filters"]["hits"]
    assert h["atr_spike"] == 0 and on["entry_filters"]["log"] == []
    assert h["atr_spike_unavailable"] > 0   # window days 60..99 have < 100 bars: filter lets them through
    assert _same_result(off, on)


def test_f2_atr_spike_triggers_after_a_volatility_jump_and_matches_an_independent_recompute(monkeypatch):
    pack = _pack(widen_from=100)
    off, _ = _simulate(monkeypatch, pack, 2_000_000)
    on, log_on = _simulate(monkeypatch, _pack(widen_from=100), 2_000_000, filter_atr_spike=True)
    log = on["entry_filters"]["log"]
    assert on["entry_filters"]["hits"]["atr_spike"] > 0 and log
    hist = {c: v["hist"] for c, v in pack[0].items()}
    for r in log:
        h = hist[r["code"]]
        i = next(j for j, b in enumerate(h) if b["date"] == r["date"])
        trs = [max(h[j]["high"] - h[j]["low"], abs(h[j]["high"] - h[j - 1]["close"]), abs(h[j]["low"] - h[j - 1]["close"]))
               for j in range(i - 99, i + 1)]
        a100 = sum(trs) / 100.0
        a14 = sum(trs[-14:]) / 14.0
        assert r["reason"] == "atr_spike" and i >= 100
        assert r["atr100"] == pytest.approx(a100) and r["atr14"] == pytest.approx(a14)
        assert a14 / a100 > 1.5
    # a filtered signal day never reaches the caps for that code
    dropped = {(r["date"], r["code"]) for r in log}
    for e in log_on:
        for c in e["cands"]:
            assert (e["date"], c["code"]) not in dropped
    assert on["closed_pnls"] != off["closed_pnls"]  # the filter really changed the trade set


def test_filter_decisions_do_not_depend_on_bars_after_the_signal_day(monkeypatch):
    k = 120
    a = _pack(widen_from=100)
    b = _pack(widen_from=100)
    for code in b[0]:  # rewrite everything from bar k on
        for bar in b[0][code]["hist"][k:]:
            bar.update(high=bar["high"] * 4, low=bar["low"] / 4, open=bar["open"] * 2, close=bar["close"] * 3)
    cut_date = a[0]["AA"]["hist"][k]["date"]
    kw = dict(filter_unit_risk=True, filter_atr_spike=True)
    out_a, _ = _simulate(monkeypatch, a, 2_000_000, **kw)
    out_b, _ = _simulate(monkeypatch, b, 2_000_000, **kw)
    early_a = [r for r in out_a["entry_filters"]["log"] if r["date"] < cut_date]
    early_b = [r for r in out_b["entry_filters"]["log"] if r["date"] < cut_date]
    assert early_a and early_a == early_b
