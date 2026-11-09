# -*- coding: utf-8 -*-
"""Simulated holdings for local proxies (research only; not paper_book)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from desk.proxy_positions import PROXY_IDS, load_proxy_positions, positions_df, trade_log_df
from proxy_cta import _simulate_cs

ROOT = Path(__file__).resolve().parents[1]


def _series(n_days: int = 90, n_codes: int = 8):
    """Deterministic bars: code k drifts by (k - mid) so ranking by trend is stable."""
    d0 = date(2026, 1, 1)
    series = {}
    for k in range(n_codes):
        px, hist = 100.0, []
        for i in range(n_days):
            px *= 1.0 + (k - n_codes / 2) * 0.001
            hist.append({"date": (d0 + timedelta(days=i)).isoformat(), "close": px})
        series[f"C{k}"] = {"hist": hist, "meta": {"name": f"N{k}", "mult": 10}}
    return series


def test_final_positions_match_rules_and_are_separate_fields():
    series = _series()
    # carry empty → score falls back to trend (T) for cwft; top codes = highest drift.
    out = _simulate_cs(series, {}, name="proxy_cwft", mode="cwft", top_n=3)
    assert out["ok"]
    assert out["positions_kind"] == "research_simulated_not_live"
    pos = out["final_positions"]
    assert len(pos) == 6
    longs = {p["code"] for p in pos if p["direction"] == "long"}
    shorts = {p["code"] for p in pos if p["direction"] == "short"}
    assert longs == {"C5", "C6", "C7"}
    assert shorts == {"C0", "C1", "C2"}
    assert all(abs(abs(p["weight"]) - 1 / 6) < 1e-5 for p in pos)
    assert abs(sum(p["weight"] for p in pos)) < 1e-9  # dollar-neutral
    assert out["positions_asof"] == out["end"] == series["C0"]["hist"][-1]["date"]
    # Stable ranking → held since first scored day; unrealized sign follows direction.
    for p in pos:
        assert p["entry_date"] == series["C0"]["hist"][61]["date"]
        assert p["entry_price"] and p["last_price"] and p["lots_equiv"] > 0
        assert (p["unrealized_pct"] > 0)  # longs rose, shorts fell
    # Opens logged once, no closes for a stable book.
    assert [t["action"] for t in out["trade_log"]].count("open") == 6
    assert all(t["action"] == "open" for t in out["trade_log"])


def test_flip_logs_close_with_pnl_and_resets_entry():
    series = _series()
    # Reverse C0's trend for the last 15 bars so it drops out of the short book.
    hist = series["C0"]["hist"]
    px = hist[-16]["close"]
    for bar in hist[-15:]:
        px *= 1.03
        bar["close"] = px
    out = _simulate_cs(series, {}, name="proxy_cwft", mode="cwft", top_n=3)
    closes = [t for t in out["trade_log"] if t["action"] == "close"]
    assert closes and all(t["pnl_pct"] is not None for t in closes)
    assert "C0" not in {p["code"] for p in out["final_positions"] if p["direction"] == "short"}


def test_equity_curve_unchanged_by_holdings_tracking():
    """Equity must follow close[t]→close[t+1] on the day's picks (pre-existing rule)."""
    series = _series()
    out = _simulate_cs(series, {}, name="proxy_cwft", mode="cwft", top_n=3)
    curve = out["equity_curve"]
    # Stable book: daily ret = mean(long r) - mean(short r) over 6 legs, /6 scaling already.
    k_hi = [5, 6, 7]
    k_lo = [0, 1, 2]
    r = lambda k: (1.0 + (k - 4) * 0.001) - 1.0
    day = (sum(r(k) for k in k_hi) - sum(r(k) for k in k_lo)) / 6
    assert abs(curve[-2]["equity"] / curve[-3]["equity"] - (1 + day)) < 1e-6


def test_loader_soft_fails_on_missing_and_old_json(tmp_path):
    d = tmp_path / "external" / "strategies"
    d.mkdir(parents=True)
    (d / "proxy_cwft.json").write_text(json.dumps({"name": "x", "end": "2026-11-09"}), encoding="utf-8")
    (d / "proxy_frontnext_st.json").write_text("{not json", encoding="utf-8")
    recs = {r["id"]: r for r in load_proxy_positions(tmp_path)}
    assert set(recs) == set(PROXY_IDS)
    assert recs["proxy_cwft"]["status"] == "no_positions"
    assert recs["proxy_frontnext_st"]["status"] == "missing"
    assert recs["proxy_long_short_cwft"]["status"] == "missing"
    assert positions_df([]).empty and trade_log_df([]).empty


def test_repo_proxy_artifacts_have_own_holdings_and_paper_book_untouched():
    recs = load_proxy_positions(ROOT)
    for r in recs:
        assert r["status"] in {"ready", "flat", "no_positions"}
    ready = [r for r in recs if r["status"] == "ready"]
    if ready:
        for r in ready:
            df = positions_df(r["positions"])
            assert {"品种", "方向", "权重%", "入场日"} <= set(df.columns)
    book = json.loads((ROOT / "paper_book_latest.json").read_text(encoding="utf-8"))
    assert not any("proxy" in json.dumps(book.get(k, "")) for k in ("positions", "open_positions"))
