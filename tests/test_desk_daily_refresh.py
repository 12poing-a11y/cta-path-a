# -*- coding: utf-8 -*-
from __future__ import annotations

from research.desk_daily_refresh import (
    CORE_STEPS,
    HEAVY_STEPS,
    SKIPPED_BY_POLICY,
    WRITE_BOUNDS,
    refresh_desk_research,
    refresh_desk_research_split,
)


def _stub_all(monkeypatch) -> None:
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_gamma_wall_collect",
        lambda root: (_ for _ in ()).throw(RuntimeError("skip collect")),
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_ablation",
        lambda root: {"ok": True, "path": "data/ablation/strategy_indicator_ablation_latest.json"},
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_blend",
        lambda root: {"ok": True, "path": "data/ablation/strategy_blend_latest.json"},
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_ic",
        lambda root: {"ok": True, "path": "lab/research/ic/ic_groups_latest.json"},
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_oos",
        lambda root: {"ok": True, "path": "lab/research/oos/oos_vs_path_a_latest.json"},
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_portfolio",
        lambda root: {"ok": True, "path": "lab/research/portfolio/portfolio_risk_latest.json"},
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_p4",
        lambda root: {"ok": True, "path": "lab/research/ml/p4_light_latest.json"},
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_gamma_research",
        lambda root: {"ok": True, "n_ok": 1, "contracts": ["CF2701"]},
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_lsp",
        lambda root: {"ok": True, "n_ok": 2, "n_skip": 0},
    )
    monkeypatch.setattr(
        "research.desk_daily_refresh._refresh_npd_reminders",
        lambda root: {"ok": True, "path": "data/cotton/npd_reminders_latest.json", "n": 0},
    )


def test_write_bounds_cover_packs():
    for sid in (*CORE_STEPS, *HEAVY_STEPS):
        assert sid in WRITE_BOUNDS
        assert WRITE_BOUNDS[sid].get("mutates_formal") is False


def test_refresh_desk_research_soft_on_empty_tmp(tmp_path, monkeypatch):
    _stub_all(monkeypatch)
    pack = refresh_desk_research(tmp_path, pack="all", include_gamma_wall_collect=True)
    assert pack["schema"] == "cta-desk-daily-refresh-v1"
    assert pack["n_ok"] >= 1
    assert "seconds_total" in pack
    assert (tmp_path / "lab" / "research" / "desk_daily_refresh_latest.json").is_file()
    assert any(s["id"] == "gamma_wall_collect" and not s["ok"] for s in pack["steps"])
    assert SKIPPED_BY_POLICY


def test_refresh_split_writes_pack_files(tmp_path, monkeypatch):
    _stub_all(monkeypatch)
    out = refresh_desk_research_split(tmp_path, include_gamma_wall_collect=True)
    assert out["schema"] == "cta-desk-daily-refresh-split-v1"
    assert (tmp_path / "lab" / "research" / "desk_daily_refresh_core_latest.json").is_file()
    assert (tmp_path / "lab" / "research" / "desk_daily_refresh_heavy_latest.json").is_file()
    assert (tmp_path / "lab" / "research" / "desk_daily_refresh_latest.json").is_file()
    assert out["core"]["n_ok"] >= 1
