# -*- coding: utf-8 -*-
"""Proxy factor ablation + ablation JSON schema helpers."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import importlib.util

from desk.ablation_panel import load_ablation, rows_frame
from proxy_cta import _score_day, _simulate_cs

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "strategy_indicator_ablation",
    _ROOT / "scripts" / "strategy_indicator_ablation.py",
)
_abl = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_abl)
_kpi_row = _abl._kpi_row
_summarize = _abl._summarize
_proxy_grid_for_mode = _abl.proxy_grid_for_mode
_path_a_grid_for_mode = _abl.path_a_grid_for_mode


def _series(n_days: int = 90, n_codes: int = 8):
    d0 = date(2026, 1, 1)
    series = {}
    for k in range(n_codes):
        px, hist = 100.0, []
        for i in range(n_days):
            px *= 1.0 + (k - n_codes / 2) * 0.001
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


def _idx(series):
    return {
        code: {bar["date"]: i for i, bar in enumerate(pack["hist"])}
        for code, pack in series.items()
    }


def test_ablate_T_changes_cwft_ranking_when_carry_present():
    series = _series()
    idx = _idx(series)
    d = series["C0"]["hist"][-1]["date"]
    # Strong carry on weak-trend name → C/F dominate unless ablated.
    curves = {
        "C0": {"carry": {d: (100.0, 110.0)}},  # contango → c_score negative
        "C7": {"carry": {d: (100.0, 90.0)}},  # backwardation → c_score positive
    }
    full = _score_day(series, idx, curves, d, "cwft")
    no_t = _score_day(series, idx, curves, d, "cwft", ablate={"T"})
    only_t = _score_day(series, idx, curves, d, "cwft", ablate={"C", "F"})
    assert full["C7"] > full["C0"]
    assert no_t["C7"] > no_t["C0"]
    # Only T → ranking follows drift (C7 highest index).
    ranked = sorted(only_t, key=only_t.get, reverse=True)
    assert ranked[0] == "C7"


def test_simulate_cs_ablate_flag_in_payload():
    series = _series()
    out = _simulate_cs(series, {}, name="proxy_cwft", mode="cwft", ablate={"T"})
    assert out["ok"]
    assert out.get("ablate") == ["T"]
    full = _simulate_cs(series, {}, name="proxy_cwft", mode="cwft")
    assert "ablate" not in full


def test_summarize_ranks_hurt_when_removed():
    rows = [
        _kpi_row(
            strategy_id="a", strategy_name="A", variant="full", variant_label="完整",
            ablated=[], ret_pct=10.0, max_dd_pct=5.0,
        ),
        _kpi_row(
            strategy_id="a", strategy_name="A", variant="no_X", variant_label="关X",
            ablated=["X"], ret_pct=4.0, max_dd_pct=5.0, baseline_ret=10.0, baseline_dd=5.0,
        ),
        _kpi_row(
            strategy_id="a", strategy_name="A", variant="no_Y", variant_label="关Y",
            ablated=["Y"], ret_pct=11.0, max_dd_pct=5.0, baseline_ret=10.0, baseline_dd=5.0,
        ),
    ]
    s = _summarize(rows, grid_mode="ablation")
    assert s["best_full_strategies"][0]["strategy_id"] == "a"
    assert s["most_valuable_indicators"][0]["variant"] == "no_X"
    assert s["most_valuable_indicators"][0]["delta_ret_vs_full"] == -6.0
    assert any(r["variant"] == "no_Y" for r in s["redundant_or_harmful"])


def test_full_grid_sizes():
    # cwft: C,F,T → 2^3 = 8; ls: 2^4 = 16; frontnext: 2^2 = 4
    assert len(_proxy_grid_for_mode("cwft", "full_grid")) == 8
    assert len(_proxy_grid_for_mode("long_short_cwft", "full_grid")) == 16
    assert len(_proxy_grid_for_mode("frontnext_st", "full_grid")) == 4
    # Path-A: 3 filters × 4 mom × bypass(1 if already off else 2)
    bypass_on = {"enabled": True, "extreme_gap_pct": 1.0, "action": "block", "scale": 0.5, "note": ""}
    bypass_off = {"enabled": False, "extreme_gap_pct": 1.0, "action": "block", "scale": 0.5, "note": ""}
    n_on = len(_path_a_grid_for_mode("full_grid", base_r20=3.0, base_r60=5.0, base_bypass=bypass_on))
    n_off = len(_path_a_grid_for_mode("full_grid", base_r20=3.0, base_r60=5.0, base_bypass=bypass_off))
    assert n_on == 24
    assert n_off == 12


def test_load_ablation_soft_missing(tmp_path: Path):
    assert load_ablation(tmp_path) is None
    payload = {
        "ok": True,
        "asof": "2026-11-09",
        "rows": [
            {
                "strategy_name": "A",
                "variant_label": "完整",
                "ret_pct": 1.0,
                "max_dd_pct": 2.0,
                "calmar": 0.5,
                "ok": True,
            }
        ],
        "summary": {},
    }
    path = tmp_path / "data" / "ablation" / "strategy_indicator_ablation_latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    got = load_ablation(tmp_path)
    assert got and got["asof"] == "2026-11-09"
    df = rows_frame(got)
    assert list(df.columns)[:3] == ["策略", "变体说明", "收益%"]
