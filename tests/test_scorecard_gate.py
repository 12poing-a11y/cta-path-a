# -*- coding: utf-8 -*-
"""T-GV: gate booleans derived from artifacts, not self-report."""
from __future__ import annotations

import json
from pathlib import Path

from research.governance.scorecard_gate import (
    artifact_build_ok,
    attach_gate_to_scorecard,
    evaluate_from_artifacts,
    has_stress_contrast,
    validation_from_artifacts,
)


def test_stress_contrast_detection():
    assert has_stress_contrast({"cost_scenario_contrast": {"ok": True, "rows": {"base": {}, "stress": {}}}})
    assert not has_stress_contrast({"cost_scenario_contrast": {"ok": False, "rows": {"base": {}}}})
    assert not has_stress_contrast(None)


def test_gate_from_tmp_artifacts(tmp_path: Path):
    bt = {
        "schema_version": "cta-backtest-v13-tradability",
        "proxy_entry_share": 0.2,
        "cost_scenario_contrast": {"ok": True, "rows": {"base": {"ret_pct": 1}, "stress": {"ret_pct": 0}}},
    }
    pbo = {
        "pbo": {"pbo": 0.4, "n_obs": 100, "n_trials": 5},
        "psr_primary": {"psr": 0.55},
        "dsr_primary": {"dsr": 0.2},
        "matrix_meta": {"n_obs": 100},
    }
    (tmp_path / "historical_backtest_latest.json").write_text(
        json.dumps(bt), encoding="utf-8"
    )
    pbo_dir = tmp_path / "lab" / "research" / "validation"
    pbo_dir.mkdir(parents=True)
    (pbo_dir / "pbo_path_a_latest.json").write_text(json.dumps(pbo), encoding="utf-8")

    gate = evaluate_from_artifacts(tmp_path, human_approved=False)
    assert gate["flags"]["has_cost_stress"] is True
    assert gate["flags"]["has_oos"] is True
    assert gate["validation"]["psr"]["psr"] == 0.55
    assert artifact_build_ok(gate) is True
    assert gate["pass"] is False  # human_approval still required
    assert "human_approval" in gate["hard_failures"]

    card = attach_gate_to_scorecard({"ok": True, "note": "x"}, gate)
    assert card["ok"] is True
    assert card["gate"]["auto_promote"] is False


def test_gate_build_fails_without_stress(tmp_path: Path):
    bt = {"cost_scenario_contrast": {"ok": False, "rows": {"base": {}}}}
    pbo = {"pbo": {"pbo": 0.3}, "psr_primary": {"psr": 0.5}, "dsr_primary": {"dsr": 0.1}}
    (tmp_path / "historical_backtest_latest.json").write_text(json.dumps(bt), encoding="utf-8")
    pbo_dir = tmp_path / "lab" / "research" / "validation"
    pbo_dir.mkdir(parents=True)
    (pbo_dir / "pbo_path_a_latest.json").write_text(json.dumps(pbo), encoding="utf-8")
    gate = evaluate_from_artifacts(tmp_path)
    assert gate["artifact_build_ok"] is False
    assert "cost_stress" in gate["hard_failures"]
    card = attach_gate_to_scorecard({"ok": True}, gate)
    assert card["ok"] is False


def test_validation_from_artifacts_unit():
    v = validation_from_artifacts(
        {"proxy_entry_share": 0.1},
        {"psr_primary": {"psr": 0.7}, "dsr_primary": {"dsr": 0.3}, "pbo": {"pbo": 0.2}},
    )
    assert v["psr"]["psr"] == 0.7
    assert v["pbo"]["pbo"] == 0.2
