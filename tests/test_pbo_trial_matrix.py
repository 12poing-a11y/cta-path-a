# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from pathlib import Path

from lab.validation.trial_matrix import (
    build_trial_return_matrix,
    compute_pbo_report,
    path_a_trial_specs,
    save_pbo_artifacts,
)
from lab.validation.report import validation_bundle_from_backtest


def _fake_curve(seed: float, n: int = 120):
    from datetime import date, timedelta

    eq = 200_000.0
    rows = []
    d = date(2025, 1, 1)
    i = 0
    while len(rows) < n:
        if d.weekday() < 5:
            eq *= 1.0 + 0.0003 + 0.002 * math.sin((i + seed) / 7.0)
            rows.append({"date": d.isoformat(), "equity": round(eq, 2)})
            i += 1
        d += timedelta(days=1)
    return rows


def test_path_a_trial_specs_has_current_and_grid():
    specs = path_a_trial_specs()
    assert len(specs) >= 5
    assert any(s["label"] == "current" for s in specs)
    ids = [s["trial_id"] for s in specs]
    assert len(ids) == len(set(ids))


def test_build_matrix_and_pbo(tmp_path):
    specs = [
        {"trial_id": "a", "label": "a", "stop_atr_mult": 0.8, "reward_rr": 2.0, "min_r20": 4, "min_r60": 6},
        {"trial_id": "b", "label": "b", "stop_atr_mult": 1.0, "reward_rr": 1.5, "min_r20": 4, "min_r60": 6},
        {"trial_id": "c", "label": "c", "stop_atr_mult": 1.2, "reward_rr": 2.5, "min_r20": 3, "min_r60": 5},
    ]

    def simulate_fn(cfg, mode, pack=None):
        seed = float(cfg["stop_atr_mult"]) + float(cfg["reward_rr"])
        return {
            "ok": True,
            "equity_curve": _fake_curve(seed, 160),
            "ret_pct": seed,
            "max_dd_pct": 5.0,
            "cost_yuan": 100.0,
            "closed_trades": 10,
        }

    matrix = build_trial_return_matrix(
        simulate_fn=simulate_fn,
        base_cfg={"slippage_ticks": 1.0},
        pack=({}, {}, {}),
        mode="base",
        specs=specs,
    )
    assert matrix["ok"]
    assert matrix["n_trials"] == 3
    assert matrix["n_obs"] >= 50
    assert matrix["bytes_estimate"] < 50_000
    report = compute_pbo_report(matrix, n_groups=8)
    assert report["ok"]
    assert report["pbo"]["ok"]
    assert 0.0 <= report["pbo"]["pbo"] <= 1.0
    paths = save_pbo_artifacts(report, matrix, root=tmp_path)
    assert (tmp_path / paths["matrix"]).is_file()
    assert (tmp_path / paths["report"]).is_file()
    # file size small
    assert (tmp_path / paths["matrix"]).stat().st_size < 200_000


def test_validation_bundle_merges_pbo(tmp_path, monkeypatch):
    specs = [
        {"trial_id": "a", "label": "a", "stop_atr_mult": 0.8, "reward_rr": 2.0, "min_r20": 4, "min_r60": 6},
        {"trial_id": "b", "label": "b", "stop_atr_mult": 1.0, "reward_rr": 2.0, "min_r20": 4, "min_r60": 6},
    ]

    def simulate_fn(cfg, mode, pack=None):
        return {
            "ok": True,
            "equity_curve": _fake_curve(float(cfg["stop_atr_mult"]), 160),
            "ret_pct": 1.0,
            "max_dd_pct": 4.0,
            "cost_yuan": 50,
            "closed_trades": 8,
        }

    matrix = build_trial_return_matrix(
        simulate_fn=simulate_fn,
        base_cfg={},
        pack=None,
        specs=specs,
    )
    report = compute_pbo_report(matrix, n_groups=8)
    save_pbo_artifacts(report, matrix, root=tmp_path)

    import lab.validation.trial_matrix as tm
    import lab.validation.report as vr

    monkeypatch.setattr(tm, "ROOT", tmp_path)
    monkeypatch.setattr(tm, "LATEST", tmp_path / "lab" / "research" / "validation" / "pbo_path_a_latest.json")
    # load_latest_pbo uses root / lab/...
    curve = _fake_curve(0.8, 160)
    out = {
        "ok": True,
        "equity_curve": curve,
        "equity_start": 200000,
        "schema_version": "t",
        "mode": "base",
        "cost_scenario": "base",
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
        "n_trials_assumed": 2,
    }
    # Point loader at tmp
    monkeypatch.setattr(vr, "validation_bundle_from_returns", vr.validation_bundle_from_returns)

    from lab.validation.trial_matrix import load_latest_pbo

    assert load_latest_pbo(tmp_path) is not None
    # manually merge path used inside bundle — patch load_latest_pbo
    monkeypatch.setattr(
        "lab.validation.trial_matrix.load_latest_pbo",
        lambda root=None: load_latest_pbo(tmp_path),
    )
    bundle = validation_bundle_from_backtest(out, n_trials=2)
    assert bundle["pbo"].get("ok") is True
    assert bundle.get("pbo_source")
