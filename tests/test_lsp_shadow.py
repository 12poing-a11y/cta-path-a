# -*- coding: utf-8 -*-
"""LSP shadow track — causal profile sweep reclaim."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lsp_shadow import demo_bars, run_one
from signals.lsp_eval import assert_shadow_destination
from signals.lsp_profile import LspParams, build_profile, detect_lsp_sweeps
from signals.lsp_sim import simulate_lsp_trades, summarize_trades

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "configs" / "lsp" / "baseline.json"


def test_profile_causal_poc_inside_range():
    bars = demo_bars()[:50]
    snap = build_profile(bars, LspParams(lookback=48))
    assert snap is not None
    assert snap.val <= snap.poc <= snap.vah


def test_detect_finds_reclaim_signals_on_demo():
    bars = demo_bars()
    det = detect_lsp_sweeps(bars, LspParams(lookback=40, bins=16), timeframe="daily")
    assert det.profiles_sampled > 0
    dirs = {s.direction for s in det.signals}
    # Demo constructed with both sweep-high and sweep-low reclaim.
    assert "short" in dirs or "long" in dirs


def test_no_lookahead_profile_window():
    bars = demo_bars()
    params = LspParams(lookback=30, bins=12)
    # Profile at i must equal profile built from bars[i-lookback:i]
    for i in (35, 50, 60):
        if i >= len(bars):
            break
        full = detect_lsp_sweeps(bars[: i + 1], params)
        # Rebuild last window manually
        snap = build_profile(bars[i - params.lookback : i], params)
        assert snap is not None
        # Any signal on last bar uses that snap's edges
        last_sigs = [s for s in full.signals if s.signal_index == i]
        for s in last_sigs:
            assert abs(s.vah - snap.vah) < 1e-6
            assert abs(s.val - snap.val) < 1e-6


def test_simulate_and_shadow_write(tmp_path):
    bars = demo_bars()
    # Redirect shadow via monkeypatch of SHADOW_DIR is hard; call run_one then move check.
    # Use assert_shadow_destination directly.
    dest = assert_shadow_destination(ROOT, ROOT / "data" / "lsp" / "shadow" / "x.json")
    assert dest.name == "x.json"
    with pytest.raises(ValueError):
        assert_shadow_destination(ROOT, ROOT / "paper_book_latest.json")
    payload = run_one(bars, CFG, symbol="DEMO", timeframe="daily")
    assert payload["live_trading"] is False
    assert payload["formal_path_a_untouched"] is True
    assert "summary" in payload
    trades, skipped = simulate_lsp_trades(bars, detect_lsp_sweeps(bars).signals)
    summ = summarize_trades(trades)
    assert summ["n"] == len(trades)


def test_demo_runner_both_tf():
    bars = demo_bars()
    for tf in ("daily", "60"):
        payload = run_one(bars, CFG, symbol="DEMO", timeframe=tf)
        assert payload["timeframe"] == tf
        assert Path(ROOT / payload["path"]).is_file()
