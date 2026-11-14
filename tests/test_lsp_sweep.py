# -*- coding: utf-8 -*-
from __future__ import annotations

from lab.lsp import detect_sweep_events, label_events, run_lsp, summarize_events
from lab.lsp.levels import detect_swing_levels


def _bar(i, o, h, l, c, vol=100.0):
    return {
        "datetime": f"2026-01-{(i // 20) + 1:02d} {9 + (i % 20) // 4}:{(i % 4) * 15:02d}:00",
        "date": f"2026-01-{(i // 20) + 1:02d}",
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(vol),
    }


def _range_bars(n=80, base=100.0):
    rows = []
    px = base
    for i in range(n):
        # gentle oscillation then a clear swing high around mid
        if i < 30:
            px = base + (i % 5) * 0.5
        elif i == 35:
            px = base + 8  # swing high pivot
        elif 36 <= i <= 38:
            px = base + 5 - (i - 36)
        elif i == 50:
            px = base + 12  # pierce above prior high
        elif 51 <= i <= 54:
            px = base + 6  # reclaim
        else:
            px = base + 2 + (i % 3) * 0.2
        rows.append(_bar(i, px - 0.3, px + 0.8, px - 0.8, px, vol=200 if i == 50 else 80))
    return rows


def test_swing_levels_causal():
    bars = _range_bars()
    levels = detect_swing_levels(bars, swing_left=2, swing_right=2)
    highs = [lv for lv in levels if lv.kind == "high"]
    assert highs
    for lv in highs:
        assert lv.confirmed_index == lv.index + 2
        assert lv.confirmed_index < len(bars)


def test_detect_and_label_fake_break():
    bars = _range_bars()
    events = detect_sweep_events(
        bars, symbol="CF", timeframe="15m", swing_left=2, swing_right=2, min_break_atr=0.01
    )
    assert events, "expected at least one pierce"
    labeled = label_events(bars, events, reclaim_bars=5)
    assert all(e.get("outcome") for e in labeled)
    stats = summarize_events(labeled)
    assert stats["n_events"] == len(labeled)
    assert abs(sum(stats["outcome_probs"].values()) - 1.0) < 1e-6 or stats["n_events"] == 0
    assert stats.get("by_direction_detail")
    for block in (stats.get("by_direction_detail") or {}).values():
        assert "n" in block and "probs" in block and "counts" in block


def test_run_lsp_pipeline(tmp_path):
    bars = _range_bars(100)
    payload = run_lsp(bars, symbol="CF", contract="TEST", timeframe="15m")
    assert payload["ok"]
    assert payload["status"] == "Research"
    from lab.lsp.pipeline import save_lsp_run

    paths = save_lsp_run(payload, root=tmp_path)
    assert (tmp_path / paths["latest"]).is_file()
