# -*- coding: utf-8 -*-
"""fix3: weekly formal-rule lock (LF sha, params, fill_series=mixed, clean tree)."""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "ifind_call" not in sys.modules:
    stub = types.ModuleType("ifind_call")
    stub.active_slot = lambda *a, **k: None
    stub.call = lambda *a, **k: {}
    stub.usage_report = lambda: {"count": 0, "calls": []}
    sys.modules["ifind_call"] = stub

from research.execution import rule_lock as rl  # noqa: E402


def test_repo_rules_match_lock():
    info = rl.check_rules(ROOT)
    assert info["fill_series_required"] == "mixed"


def test_repo_formal_params_match_rules():
    import historical_backtest as hb

    rl.check_rules(ROOT, hb._load_cfg())


def test_crlf_hash_equals_lf(tmp_path):
    raw = (ROOT / "execution_rules.json").read_bytes().replace(b"\r\n", b"\n")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_bytes(raw)
    b.write_bytes(raw.replace(b"\n", b"\r\n"))
    assert rl.normalized_sha256(a) == rl.normalized_sha256(b)


def _mini_repo(tmp_path, rules=None):
    rules = rules or json.loads((ROOT / "execution_rules.json").read_text(encoding="utf-8"))
    (tmp_path / "configs").mkdir()
    (tmp_path / "execution_rules.json").write_text(json.dumps(rules), encoding="utf-8")
    (tmp_path / rl.LOCK_FILE).write_text(
        json.dumps({"execution_rules_sha256_lf": rl.normalized_sha256(tmp_path / "execution_rules.json"), "fill_series": "mixed"}),
        encoding="utf-8",
    )
    return rules


def test_rule_file_change_raises(tmp_path):
    rules = _mini_repo(tmp_path)
    rules["stop_atr_mult"] = 1.2
    (tmp_path / "execution_rules.json").write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(rl.RuleLockError):
        rl.check_rules(tmp_path)


def test_param_mismatch_raises(tmp_path):
    _mini_repo(tmp_path)
    with pytest.raises(rl.RuleLockError, match="stop_atr_mult"):
        rl.check_rules(tmp_path, {"stop_atr_mult": 1.2, "reward_rr": 2.0})


def test_fill_series_mismatch_raises(tmp_path):
    _mini_repo(tmp_path)
    rl.check_fill_series(tmp_path, {"fill_series": "mixed"})
    with pytest.raises(rl.RuleLockError):
        rl.check_fill_series(tmp_path, {"fill_series": "continuous_proxy"})


def test_dirty_tree_blocks_formal(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "x.py").write_text("a=1\n")
    with pytest.raises(rl.RuleLockError, match="dirty"):
        rl.check_clean(tmp_path)
    # run outputs / caches do not count as dirty
    (tmp_path / "x.py").unlink()
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "m.json").write_text("{}")
    (tmp_path / "weekly_backtest_latest.json").write_text("{}")
    rl.check_clean(tmp_path)


def test_weekly_lock_failure_writes_nothing(monkeypatch, tmp_path):
    import historical_backtest as hb
    import weekly_backtest as wb

    _mini_repo(tmp_path)
    monkeypatch.setattr(wb, "ROOT", tmp_path)
    monkeypatch.setattr(hb, "_load_cfg", lambda: {"stop_atr_mult": 1.2, "reward_rr": 2.0, "equity0": 1, "entry_filter": "seats"})
    called = []
    monkeypatch.setattr(hb, "_simulate_cfg", lambda *a, **k: called.append(1) or {})
    with pytest.raises(rl.RuleLockError):
        wb.run(7)
    assert not called
    assert not (tmp_path / "weekly_backtest_latest.json").exists()


def test_weekly_fill_series_mismatch_writes_nothing(monkeypatch, tmp_path):
    import historical_backtest as hb
    import member_rank
    import weekly_backtest as wb

    rules = _mini_repo(tmp_path)
    p = {"equity0": 200_000, "entry_filter": rules["entry_filter"], "fill_price": rules["fill_price"],
         "stop_atr_mult": rules["stop_atr_mult"], "reward_rr": rules["reward_rr"], "min_r20": rules["min_r20_pct"],
         "min_r60": rules["min_r60_pct"], "max_positions": rules["max_positions"], "max_per_bucket": rules["max_per_bucket"],
         "risk_pct": rules["risk_pct"], "availability_lag": rules["availability_lag_days"]}
    monkeypatch.setattr(wb, "ROOT", tmp_path)
    monkeypatch.setattr(hb, "_load_cfg", lambda: p)
    monkeypatch.setattr(hb, "_simulate_cfg", lambda *a, **k: {"ok": True, "fill_series": "continuous_proxy", "equity_curve": []})
    monkeypatch.setattr(member_rank, "backfill_member_lookback", lambda **kw: {})
    with pytest.raises(rl.RuleLockError, match="fill_series"):
        wb.run(7)
    assert not (tmp_path / "weekly_backtest_latest.json").exists()
