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
            # Tight range so gradual drift does not trip ATR stops in ranking tests.
            hist.append(
                {
                    "date": (d0 + timedelta(days=i)).isoformat(),
                    "open": px,
                    "high": px * 1.0005,
                    "low": px * 0.9995,
                    "close": px,
                }
            )
        series[f"C{k}"] = {"hist": hist, "meta": {"name": f"N{k}", "mult": 10}}
    return series


# Wide stops so ranking-only tests are not interrupted by ATR exits.
_WIDE = {"stop_atr_mult": 50.0, "reward_rr": 50.0}


def test_final_positions_match_rules_and_are_separate_fields():
    series = _series()
    # carry empty → score falls back to trend (T) for cwft; top codes = highest drift.
    out = _simulate_cs(series, {}, name="proxy_cwft", mode="cwft", top_n=3, **_WIDE)
    assert out["ok"]
    assert out["positions_kind"] == "research_simulated_not_live"
    assert out["stop_atr_mult"] == 50.0 and out["reward_rr"] == 50.0
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
        assert p["stop"] is not None and p["target"] is not None and p["atr"] is not None
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
        bar["open"] = px
        bar["high"] = px * 1.0005
        bar["low"] = px * 0.9995
    out = _simulate_cs(series, {}, name="proxy_cwft", mode="cwft", top_n=3, **_WIDE)
    closes = [t for t in out["trade_log"] if t["action"] == "close"]
    assert closes and all(t["pnl_pct"] is not None for t in closes)
    assert all(t.get("reason") == "signal" for t in closes)
    assert "C0" not in {p["code"] for p in out["final_positions"] if p["direction"] == "short"}


def test_equity_follows_overnight_marks_when_book_stable():
    """With a stable book and wide stops, equity still moves; no ATR exits."""
    series = _series()
    out = _simulate_cs(series, {}, name="proxy_cwft", mode="cwft", top_n=3, **_WIDE)
    assert out["ok"]
    assert out.get("stop_atr_mult") == 50.0 and out.get("reward_rr") == 50.0
    curve = out["equity_curve"]
    assert len(curve) >= 3
    assert curve[-1]["equity"] != curve[0]["equity"]
    assert out["exit_counts"]["stop"] == 0
    assert out["exit_counts"]["target"] == 0


def test_atr_stop_closes_long_and_logs_reason():
    """After entry, a crash through stop must exit with reason=stop."""
    series = _series(n_days=80, n_codes=8)
    hist = series["C7"]["hist"]
    for bar in hist[40:62]:
        c = bar["close"]
        bar["high"] = c * 1.05
        bar["low"] = c * 0.95
    crash = hist[62]
    orig = crash["close"]
    crash["open"] = orig * 0.5
    crash["high"] = orig * 0.55
    crash["low"] = orig * 0.40
    crash["close"] = orig * 0.45
    # Huge reward_rr so take-profit cannot fire before the stop crash.
    out = _simulate_cs(
        series, {}, name="proxy_cwft", mode="cwft", top_n=3,
        stop_atr_mult=1.2, reward_rr=100.0,
    )
    assert out["ok"]
    stops = [t for t in out["trade_log"] if t.get("action") == "close" and t.get("reason") == "stop"]
    assert stops, "expected at least one stop exit"
    assert any(t["code"] == "C7" for t in stops)
    assert out["exit_counts"]["stop"] >= 1


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
            assert {"品种", "方向", "权重%", "入场日", "止损", "止盈", "ATR"} <= set(df.columns)
            tdf = trade_log_df(r["trade_log"])
            if not tdf.empty:
                assert "原因" in tdf.columns
    book = json.loads((ROOT / "paper_book_latest.json").read_text(encoding="utf-8"))
    assert not any("proxy" in json.dumps(book.get(k, "")) for k in ("positions", "open_positions"))
