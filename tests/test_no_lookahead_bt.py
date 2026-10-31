# -*- coding: utf-8 -*-
"""P0: historical_backtest must not use seat/basis data published after the fill."""
from __future__ import annotations

import hashlib
import json
import math
import sys
import types
from pathlib import Path

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

N = 140


def _dates(n=N):
    from datetime import date, timedelta
    d, out = date(2025, 1, 1), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _pack():
    dates = _dates()
    series = {}
    for k, code in enumerate(("AA", "BB", "CC")):
        hist = []
        for i, d in enumerate(dates):
            c = 1000 * (1 + 0.004 * i) + 15 * math.sin(i / 3 + k)
            hist.append({"date": d, "open": c - 2, "high": c + 8, "low": c - 8, "close": c, "volume": 1})
        series[code] = {"meta": {"code": code, "name": code, "mult": 10, "bucket": code}, "hist": hist}
    return series, {}, {}


def _run(monkeypatch, mode, **kw):
    seen = []

    def fake_block(m, hist, i, direction, d, code, a, curves, member, peers):
        seen.append((d, (member.get(code) or {}).get(d), ((curves.get(code) or {}).get("carry") or {}).get(d)))
        return None

    def books(dates, codes):
        return {c: {d: {"asof": d, "inst": 1.0, "foreign": 0.0, "holder": 0.0} for d in dates} for c in codes}

    monkeypatch.setattr(hb, "entry_block", fake_block)
    monkeypatch.setattr(hb, "seat_decision", lambda direction, book: (None, "t"))
    monkeypatch.setattr(hb, "load_member_seats", books)
    monkeypatch.setattr(hb, "load_member_changes", lambda dates, codes: {c: {d: {"asof": d} for d in dates} for c in codes})
    monkeypatch.setattr(hb, "load_curves", lambda codes, **k: {c: {"carry": {d: {"asof": d} for d in _dates()}} for c in codes})
    pk = _pack()
    out = hb.simulate([v["meta"] for v in pk[0].values()], 200_000, mode=mode, pack=pk, min_r20=0.5, min_r60=0.5, **kw)
    return out, seen


def test_lag_helper_uses_previous_session_only():
    ds = _dates(5)
    got = hb.lag_by_trade_dates({d: d for d in ds}, ds, 1)
    assert ds[0] not in got
    assert all(v < d for d, v in got.items())
    assert got[ds[3]] == ds[2]
    assert hb.lag_by_trade_dates({d: d for d in ds}, ds, 0)[ds[3]] == ds[3]


def test_no_lookahead_seats(monkeypatch):
    out, seen = _run(monkeypatch, "seats")
    rows = [(d, m) for d, m, _ in seen if m is not None]
    assert rows, "seat filter never consulted"
    assert all(m["asof"] < d for d, m in rows)
    assert out.get("availability_lag") == 1


def test_no_lookahead_member_changes(monkeypatch):
    _out, seen = _run(monkeypatch, "member")
    rows = [(d, m) for d, m, _ in seen if m is not None]
    assert rows and all(m["asof"] < d for d, m in rows)


def test_no_lookahead_basis(monkeypatch):
    _out, seen = _run(monkeypatch, "carry")
    rows = [(d, c) for d, _, c in seen if c is not None]
    assert rows, "carry never consulted"
    assert all(c["asof"] < d for d, c in rows)


def test_no_lookahead_fill_next_open(monkeypatch):
    out, _ = _run(monkeypatch, "base", fill_price="next_open")
    ser = _pack()[0]
    hist = {(c, h["date"]): h for c, v in ser.items() for h in v["hist"]}
    trades = out.get("closed_pnls") or []
    assert trades, "no trades"
    for t in trades:
        assert abs(t["entry"] - hist[(t["code"], t["entry_date"])]["open"]) < 1e-3
    out_c, _ = _run(monkeypatch, "base", fill_price="close")
    for t in out_c.get("closed_pnls") or []:
        assert abs(t["entry"] - hist[(t["code"], t["entry_date"])]["close"]) < 1e-3
    assert out["fill_price"] == "next_open" and out_c["fill_price"] == "close"


def test_next_open_fill_keeps_stop_distance():
    hist = [{"date": "d0", "open": 9, "close": 10}, {"date": "d1", "open": 12, "close": 11}]
    c = hb.next_open_fill({"entry": 10.0, "stop": 8.0, "target": 14.0}, hist, 0)
    assert c["entry"] == 12 and c["stop"] == 10 and c["target"] == 16 and c["entry_date"] == "d1"
    assert hb.next_open_fill({"entry": 11.0, "stop": 9.0, "target": 15.0}, hist, 1) is None


def test_compare_does_not_rewrite_universe(tmp_path):
    (tmp_path / "universe.json").write_text('{"entry_filter": "seats"}', encoding="utf-8")
    p = hb._write_entry_filter("carry", root=tmp_path)
    assert json.loads((tmp_path / "universe.json").read_text())["entry_filter"] == "seats"
    assert json.loads(p.read_text())["entry_filter"] == "carry"


def test_input_snapshot_sha(tmp_path):
    hb._LAST_PACK.clear()
    hb._LAST_PACK.update({"series": _pack()[0], "sources": {}, "errors": {}})
    info = hb.write_input_snapshot({"end": "2025-06-30"}, ["--x"], root=tmp_path)
    blob = (tmp_path / info["path"]).read_bytes()
    assert hashlib.sha256(blob).hexdigest() == info["sha256"]
    assert info["symbols"] == 3
