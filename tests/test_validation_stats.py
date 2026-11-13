# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import random

from lab.validation import (
    deflated_sharpe_ratio,
    effective_trials,
    probability_of_backtest_overfitting,
    probabilistic_sharpe_ratio,
    validation_bundle_from_returns,
    walk_forward_segments,
)
from research.governance import evaluate_strategy_gate, register_experiment
from portfolio import align_strategy_returns, corr_matrix


def _gbm(n=300, mu=0.0004, sigma=0.01, seed=1):
    rng = random.Random(seed)
    return [mu + sigma * rng.gauss(0, 1) for _ in range(n)]


def test_psr_positive_edge_high():
    rets = _gbm(400, mu=0.001, sigma=0.008, seed=2)
    out = probabilistic_sharpe_ratio(rets, sr_benchmark=0.0)
    assert out["ok"] and out["psr"] > 0.5


def test_dsr_penalizes_many_trials():
    rets = _gbm(250, mu=0.0005, sigma=0.01, seed=3)
    one = deflated_sharpe_ratio(rets, n_trials=1)
    many = deflated_sharpe_ratio(rets, n_trials=50, mean_abs_corr=0.0)
    assert one["ok"] and many["ok"]
    assert many["dsr"] <= one["dsr"] + 1e-9
    assert many["n_eff"] == 50


def test_effective_trials_corr_reduces_n():
    et = effective_trials(10, mean_abs_corr=0.5)
    assert et["n_eff"] == 10 * 0.5 + 0.5


def test_pbo_needs_matrix_and_runs():
    # Build 4 mildly different series
    base = _gbm(320, seed=4)
    mat = []
    for i in range(320):
        mat.append(
            [
                base[i],
                base[i] + 0.0001 * math.sin(i),
                base[i] - 0.0001 * math.cos(i),
                base[i] * 0.5,
            ]
        )
    out = probability_of_backtest_overfitting(mat, n_groups=8, max_combos=200)
    assert out["ok"]
    assert 0.0 <= out["pbo"] <= 1.0
    single = probability_of_backtest_overfitting([[r] for r in base], n_groups=8)
    assert single["ok"] is False


def test_walk_forward_and_bundle():
    rets = _gbm(200, seed=5)
    wf = walk_forward_segments(rets, n_folds=4)
    assert wf["ok"] and len(wf["folds"]) >= 3
    bundle = validation_bundle_from_returns(rets, n_trials=4)
    assert bundle["psr"]["ok"]
    assert bundle["admission"]["auto_promote"] is False


def test_strategy_gate_blocks_auto_promote():
    gate = evaluate_strategy_gate(
        {"psr": {"psr": 0.9}, "dsr": {"dsr": 0.8}, "pbo": {"error": "trial_matrix_required"}},
        has_oos=True,
        has_cost_stress=True,
        beats_path_a=True,
        human_approved=False,
    )
    assert gate["auto_promote"] is False
    assert gate["pass"] is False
    assert "human_approval" in gate["hard_failures"]


def test_register_experiment_tmp(tmp_path, monkeypatch):
    import research_experiment as re

    monkeypatch.setattr(re, "ROOT", tmp_path)
    monkeypatch.setattr(re, "LOG_DIR", tmp_path / "data" / "experiments")
    re.LOG_DIR.mkdir(parents=True)
    monkeypatch.setattr(re, "LATEST", re.LOG_DIR / "latest.json")
    monkeypatch.setattr(re, "LEDGER", re.LOG_DIR / "ledger.jsonl")
    from research.governance import experiment_registry as er

    row = er.register_experiment(
        name="unit_test",
        kind="validation",
        metrics={"ret_pct": 1.0},
        validation={"psr": {"psr": 0.6}},
        status="Research",
        root=tmp_path,
    )
    assert row["status"] == "Research"
    assert (tmp_path / "data" / "experiments" / "ledger.jsonl").is_file()


def test_portfolio_corr_align():
    curves = {
        "a": [{"date": "2025-01-02", "equity": 100}, {"date": "2025-01-03", "equity": 101}, {"date": "2025-01-06", "equity": 102}],
        "b": [{"date": "2025-01-02", "equity": 100}, {"date": "2025-01-03", "equity": 100.5}, {"date": "2025-01-06", "equity": 101}],
    }
    names, dates, mat = align_strategy_returns(curves)
    assert names == ["a", "b"]
    assert len(dates) == 2
    c = corr_matrix(mat)
    assert len(c) == 2 and abs(c[0][0] - 1.0) < 1e-9
