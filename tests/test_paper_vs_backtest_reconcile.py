# -*- coding: utf-8 -*-
"""R5b: the paper book, run day by day, must book exactly what ``simulate`` books.

Offline (frozen snapshot bars / seat / carry books, repo contract + minute caches, no network).
``simulate`` runs over the full window with ``state_log``; the paper book is seeded with the
backtest's state at the close of the day before the last ``N_DAYS`` sessions (open positions, the
orders selected that day as pending, equity) and then advanced one session at a time with ONLY the
bars up to that session (``daily_update.compute_signals`` + ``paper_book.plan_entries`` +
``paper_book.advance_engine_book``).

* closed trades (code, direction, lots, entry_date, entry, exit_date, exit, reason,
  fill_price_basis, fill_contract) identical;
* every day's new pending orders == simulate's selection of that day, and the next session's fills
  == simulate's new positions;
* daily equity: paper = simulate + entry costs of the day's not-yet-filled orders (simulate charges
  them on the signal day, the paper book when they fill); max deviation reported.
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

N_DAYS = 40
EQ_TOL = 1e-4  # 0.01 %
TRADE_KEYS = ("code", "direction", "lots", "entry_date", "entry", "exit_date", "exit", "reason",
              "fill_price_basis", "fill_contract")


@pytest.fixture(scope="module")
def world():
    import historical_backtest as hb

    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    bt = json.loads(BT.read_text(encoding="utf-8"))
    mp = pytest.MonkeyPatch()
    mp.setattr(hb, "prepare_pack_for_execution", lambda pack, root=None: bt.get("contract_pack") or {})
    mp.setattr(hb, "load_member_seats", lambda dates, codes: snap["member"])
    mp.setattr(hb, "load_member_changes", lambda dates, codes: snap["member"])
    mp.setattr(hb, "lag_member", lambda mm, dates, lag: mm)
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
    p = hb._load_cfg()
    series = {}
    for u in p["cfg"]["symbols"]:
        if u["code"] in snap["bars"]:
            series[u["code"]] = {"meta": dict(u), "hist": copy.deepcopy(snap["bars"][u["code"]])}
    pack = (series, dict(snap.get("errors") or {}), dict(snap.get("sources") or {}))
    clog: list = []
    slog: list = []
    res = hb._simulate_cfg(p, p["entry_filter"], pack=pack, candidate_log=clog, contract_root=ROOT, state_log=slog)
    assert res.get("ok"), res.get("error")
    yield {"hb": hb, "p": p, "snap": snap, "curves": curves, "res": res, "clog": clog, "slog": slog,
           "meta": {c: s["meta"] for c, s in series.items()}}
    mp.undo()


class PaperRunner:
    """Drives ``paper_book.advance_engine_book`` over the snapshot, one session at a time."""

    def __init__(self, world, *, load_minute=None):
        import daily_update as du
        import paper_book as pb

        self.w, self.du, self.pb = world, du, pb
        self.settings = pb.engine_settings(world["p"])
        self.days = [e["date"] for e in world["slog"]]
        self.load_minute = load_minute
        self.engines: dict = {}
        self.plans: dict = {}

    def bars_upto(self, day):
        out = {}
        for c in self.w["meta"]:
            hist = self.w["snap"]["bars"][c]
            k = max((j for j, b in enumerate(hist) if b["date"] <= day), default=None)
            if k is not None:
                out[c] = copy.deepcopy(hist[: k + 1])
        return out

    def engine_for_day(self, day):
        from signal_core import build_signal_inputs

        bars = self.bars_upto(day)
        series = {c: {"meta": dict(m), "hist": bars[c]} for c, m in self.w["meta"].items() if c in bars}
        main_map, adj = build_signal_inputs(series, root=ROOT)
        eng = self.pb.build_engine(series, self.settings, main_map=main_map, adj=adj, contract_root=ROOT,
                                   minute_root=ROOT)
        if self.load_minute is not None:
            eng._load_minute = self.load_minute
        eng._bars = bars
        self.engines[day] = eng
        return eng

    def plan_for_day(self, eng, pos, day, sizing_raw):
        hb, p, du = self.w["hb"], self.w["p"], self.du
        sizing_eq, risk = self.pb.sizing_for(sizing_raw, self.settings)
        universe = [dict(m) for c, m in self.w["meta"].items() if c in eng._bars]
        snapm = self.w["snap"]["member"]
        _sigs, info = du.compute_signals(
            universe,
            eng._bars,
            mode=p["entry_filter"],
            bypass=hb.carry_bypass_cfg(p.get("carry_bypass")),
            vbypass=hb.vol_bypass_cfg(p.get("vol_bypass")),
            curves=self.w["curves"],
            member_loader=lambda dates, codes: snapm,
            risk_budget=risk,
            contract_root=ROOT,
            min_seat_days=p.get("min_seat_days", hb.MIN_SEAT_DAYS),
            observe_min_lots=0,
            day=day,
            inputs=(eng.main_map, eng.adj),
        )
        sel, meta = self.pb.plan_entries(info["core"], eng=eng, pos=pos, day=day, sizing_equity=sizing_eq,
                                         settings=self.settings)
        self.plans[day] = {"sizing_eq": sizing_eq, "risk": risk, "selected": sel}
        return sel, meta

    def prev_day(self, d):
        i = self.days.index(d)
        return self.days[i - 1] if i > 0 else None

    def next_day(self, d):
        i = self.days.index(d)
        return self.days[i + 1] if i + 1 < len(self.days) else None

    def advance(self, book, day):
        return self.pb.advance_engine_book(
            book, day, engine_for_day=self.engine_for_day, plan_for_day=self.plan_for_day,
            prev_day_fn=self.prev_day, next_day_fn=self.next_day,
        )

    def seed(self, s0):
        e = next(x for x in self.w["slog"] if x["date"] == s0)
        pos = {c: copy.deepcopy(q) for c, q in e["pos"].items() if str(q.get("entry_date") or "") <= s0}
        pending = [dict(c, signal_date=s0) for c in e["selected"]]
        return self.pb.seed_engine_book(
            asof=s0, positions=pos, pending=pending, equity=e["equity"] + e["entry_cost"],
            source="test:simulate_state", settings=self.settings,
        )


def _trade(row, *, exit_date_key):
    out = {k: row.get(k) for k in TRADE_KEYS if k not in ("exit_date",)}
    out["exit_date"] = row.get(exit_date_key)
    out["entry"] = round(float(out["entry"]), 4)
    out["exit"] = round(float(out["exit"]), 4)
    out["lots"] = int(out["lots"])
    return out


def _cand_key(c):
    return (c["code"], c["direction"], int(c["lots"]), round(float(c["entry"]), 9), round(float(c["stop"]), 9),
            round(float(c["target"]), 9), c.get("bucket"))


@pytest.fixture(scope="module")
def run(world):
    pr = PaperRunner(world)
    days = pr.days
    s0 = days[-N_DAYS - 1]
    window = days[-N_DAYS:]
    book = pr.seed(s0)
    books = {}
    for d in window:
        book = pr.advance(book, d)
        books[d] = book
    return {"pr": pr, "s0": s0, "window": window, "books": books}


def test_window(world, run):
    assert len(run["window"]) == N_DAYS
    assert run["window"][-1] == world["slog"][-1]["date"]


def test_trades_identical(world, run):
    s0 = run["s0"]
    sim = [_trade(t, exit_date_key="date") for t in world["res"]["closed_pnls"] if t["date"] > s0]
    paper = []
    for d in run["window"]:
        for r in run["books"][d]["closed_today"]:
            paper.append(_trade(r, exit_date_key="exit_date"))
    assert paper == sim
    print(f"closed trades compared: {len(sim)}")


def test_pending_equals_sim_selection_and_fills(world, run):
    slog = {e["date"]: e for e in world["slog"]}
    n_sel = n_fill = 0
    window = run["window"]
    for k, d in enumerate(window):
        book = run["books"][d]
        new_pending = [c for c in book["pending"] if c.get("signal_date") == d]
        want = [_cand_key(c) for c in slog[d]["selected"]]
        assert [_cand_key(c) for c in new_pending] == want, (d,)
        n_sel += len(want)
        # fills on d == simulate's positions entered from the previous session's selection
        prev = window[k - 1] if k > 0 else run["s0"]
        sim_new = {
            c: q for c, q in slog[prev]["pos"].items() if str(q.get("entry_date") or "") > prev
        }
        got = {r["code"]: r for r in book["opened_today"]}
        assert sorted(got) == sorted(sim_new), (d, sorted(got), sorted(sim_new))
        for c, q in sim_new.items():
            r = got[c]
            assert r["entry_date"] == q["entry_date"] and r["lots"] == q["lots"], (d, c)
            assert abs(float(r["entry"]) - float(q["entry"])) < 1e-9, (d, c)
            assert abs(float(r["stop"]) - float(q["stop"])) < 1e-9 and abs(float(r["target"]) - float(q["target"])) < 1e-9
            assert r.get("fill_price_basis") == q.get("fill_price_basis")
            assert r.get("fill_contract") == q.get("fill_contract")
            assert r.get("held_contract") == q.get("held_contract")
        n_fill += len(sim_new)
    print(f"pending == simulate selection on {len(window)} days ({n_sel} orders, {n_fill} fills)")


def test_positions_and_equity_track_simulate(world, run):
    slog = {e["date"]: e for e in world["slog"]}
    max_adj = max_raw = 0.0
    for d in run["window"]:
        book = run["books"][d]
        e = slog[d]
        held_sim = {c: q for c, q in e["pos"].items() if str(q.get("entry_date") or "") <= d}
        assert sorted(book["positions"]) == sorted(held_sim), d
        for c, q in held_sim.items():
            b = book["positions"][c]
            for k in ("direction", "lots", "entry_date", "held_contract", "fill_price_basis", "fill_contract",
                      "pending_roll"):
                assert b.get(k) == q.get(k), (d, c, k)
            for k in ("entry", "stop", "target", "last_mark"):
                if q.get(k) is not None:
                    assert abs(float(b[k]) - float(q[k])) < 1e-9, (d, c, k)
        adj = abs(book["equity_mtm"] - (e["equity"] + e["entry_cost"])) / e["equity"]
        raw = abs(book["equity_mtm"] - e["equity"]) / e["equity"]
        max_adj, max_raw = max(max_adj, adj), max(max_raw, raw)
        assert abs(book["equity_mark"] - round(book["equity"] + book["equity_floating"], 2)) <= 0.011
    assert max_adj <= EQ_TOL, max_adj
    assert max_raw <= 0.005, max_raw  # acceptance 0.5 %
    print(f"max equity diff: {max_adj:.3e} (same-basis) · {max_raw:.3e} (raw, incl. unfilled entry costs)")


def test_same_day_double_run_is_noop(world, run):
    pr = run["pr"]
    d = run["window"][-5]
    book = run["books"][d]
    again = pr.advance(copy.deepcopy(book), d)
    assert again.get("noop") is True
    strip = lambda b: {k: v for k, v in b.items() if k != "noop"}  # noqa: E731
    assert json.dumps(strip(again), sort_keys=True, default=str) == json.dumps(strip(book), sort_keys=True,
                                                                                default=str)
    # rerun after a changed base input (e.g. a corrected report) recomputes from the base, not on top
    nxt = run["window"][-4]
    once = pr.advance(copy.deepcopy(book), nxt)
    twice = pr.advance(copy.deepcopy(once), nxt)
    assert twice.get("noop") is True and twice["equity_mtm"] == once["equity_mtm"]
    assert len(twice["trade_ledger"]) == len(once["trade_ledger"])


def test_daily_fallback_closes_when_minutes_missing(world, run):
    """No 15m bars at all → the stop / target is still tested on the day's OHLC (the legacy paper
    book skipped the position: no minutes = no exit)."""
    s0 = run["s0"]
    sim_hits = [t for t in world["res"]["closed_pnls"] if t["date"] > s0 and t["reason"] in ("stop", "target")]
    if not sim_hits:
        pytest.skip("no stop/target exit in the window")
    t = sim_hits[0]
    pr = PaperRunner(world, load_minute=lambda *a, **k: [])
    window = run["window"]
    k = window.index(t["date"])
    prev = window[k - 1] if k > 0 else s0
    book = run["books"][prev] if prev in run["books"] else run["pr"].seed(s0)
    out = pr.advance(copy.deepcopy(book), t["date"])
    eng = pr.engines[t["date"]]
    closed = {r["code"]: r for r in out["closed_today"]}
    assert t["code"] in closed, (t, sorted(closed))
    assert closed[t["code"]]["reason"] in ("stop", "target")
    assert eng.stats["minute_manage_checks"] == 0 and eng.stats["daily_exit_fallback_n"] >= 1
