# -*- coding: utf-8 -*-
"""Pure-function coverage for desk.final_signal action口径."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.final_signal import (  # noqa: E402
    build_final_signal_board,
    build_final_signal_row,
    infer_desk_regime_key,
    project_stop_target,
    resolve_final_action,
    sentiment_hard_veto,
)


def test_hold_when_book_matches_decision():
    action, tip = resolve_final_action(
        held=True,
        held_side="多",
        mark=3500.0,
        stop=3200.0,
        target=3800.0,
        atr=100.0,
        decision_conclusion="偏多",
        l1_selected=True,
        l1_conflict=False,
        sentiment={"direction": "多", "conviction_pct": 40},
        path_a_ok=True,
    )
    assert action == "持有"
    assert "同向" in tip


def test_stop_alert_when_mark_breaches_stop():
    action, tip = resolve_final_action(
        held=True,
        held_side="多",
        mark=3190.0,
        stop=3200.0,
        target=3800.0,
        atr=100.0,
        decision_conclusion="偏多",
        l1_selected=True,
        l1_conflict=False,
        sentiment={"direction": "多", "conviction_pct": 40},
        path_a_ok=True,
    )
    assert action == "止损预警"
    assert "止损" in tip


def test_target_alert_near_target_within_01_atr():
    # target 3800, atr 100 → near if mark >= 3790
    action, tip = resolve_final_action(
        held=True,
        held_side="多",
        mark=3795.0,
        stop=3200.0,
        target=3800.0,
        atr=100.0,
        decision_conclusion="偏多",
        l1_selected=True,
        l1_conflict=False,
        sentiment={"direction": "多", "conviction_pct": 40},
        path_a_ok=True,
    )
    assert action == "止盈预警"
    assert "止盈" in tip


def test_suggest_open_flat_selected_bullish():
    action, tip = resolve_final_action(
        held=False,
        held_side=None,
        mark=None,
        stop=None,
        target=None,
        atr=None,
        decision_conclusion="偏多",
        l1_selected=True,
        l1_conflict=False,
        sentiment={"direction": "多", "conviction_pct": 50},
        path_a_ok=True,
        l1_side="多",
    )
    assert action == "建议开"
    assert "同向" in tip


def test_suggest_open_requires_l1_same_direction():
    # L1 空 vs decision 偏多 → not 建议开
    action, tip = resolve_final_action(
        held=False,
        held_side=None,
        mark=None,
        stop=None,
        target=None,
        atr=None,
        decision_conclusion="偏多",
        l1_selected=True,
        l1_conflict=False,
        sentiment={"direction": "多", "conviction_pct": 50},
        path_a_ok=True,
        l1_side="空",
    )
    assert action == "观望"
    assert action != "建议开"
    assert "不一致" in tip or "同向" not in tip


def test_suggest_open_blocked_without_l1_side():
    action, tip = resolve_final_action(
        held=False,
        held_side=None,
        mark=None,
        stop=None,
        target=None,
        atr=None,
        decision_conclusion="偏多",
        l1_selected=True,
        l1_conflict=False,
        sentiment={"direction": "多", "conviction_pct": 50},
        path_a_ok=True,
        l1_side=None,
    )
    assert action == "观望"
    assert "同向" not in tip


def test_held_decision_unavailable_stays_watch_not_close():
    action, tip = resolve_final_action(
        held=True,
        held_side="多",
        mark=3500.0,
        stop=3200.0,
        target=3800.0,
        atr=100.0,
        decision_conclusion="观望",
        l1_selected=False,
        l1_conflict=False,
        sentiment={"direction": "多", "conviction_pct": 40},
        path_a_ok=True,
        decision_available=False,
    )
    assert action == "观望"
    assert "决策不可用" in tip


def test_sentiment_hard_veto_forces_flat_or_watch():
    assert sentiment_hard_veto(
        {"direction": "空", "conviction_pct": 65}, "多"
    )
    assert not sentiment_hard_veto(
        {"direction": "空", "conviction_pct": 40}, "多"
    )

    # Held + hard veto → 建议平
    action, tip = resolve_final_action(
        held=True,
        held_side="多",
        mark=3500.0,
        stop=3200.0,
        target=3800.0,
        atr=100.0,
        decision_conclusion="偏多",
        l1_selected=True,
        l1_conflict=False,
        sentiment={"direction": "空", "conviction_pct": 70},
        path_a_ok=True,
    )
    assert action == "建议平"
    assert "情绪" in tip

    # Flat + selected + bullish decision but hard veto → 观望
    action2, tip2 = resolve_final_action(
        held=False,
        held_side=None,
        mark=None,
        stop=None,
        target=None,
        atr=None,
        decision_conclusion="偏多",
        l1_selected=True,
        l1_conflict=False,
        sentiment={"direction": "空", "conviction_pct": 70},
        path_a_ok=True,
        l1_side="多",
    )
    assert action2 == "观望"
    assert "情绪" in tip2


def test_suggest_close_when_decision_choppy():
    action, tip = resolve_final_action(
        held=True,
        held_side="空",
        mark=850.0,
        stop=870.0,
        target=820.0,
        atr=15.0,
        decision_conclusion="观望",
        l1_selected=False,
        l1_conflict=False,
        sentiment={"direction": "震荡", "conviction_pct": 20},
        path_a_ok=True,
    )
    assert action == "建议平"
    assert "观望" in tip or "反向" in tip


def test_row_suggest_open_projects_stop_target(tmp_path: Path):
    rules = {"stop_atr_mult": 1.2, "reward_rr": 1.5}
    (tmp_path / "execution_rules.json").write_text(
        '{"ok": true, "stop_atr_mult": 1.2, "reward_rr": 1.5}',
        encoding="utf-8",
    )
    sig = {
        "code": "MA",
        "name": "甲醇",
        "direction": "多",
        "selected": True,
        "lots_l1": 2,
        "close": 3400.0,
        "atr": 100.0,
    }
    proj = project_stop_target(sig, root=tmp_path, rules=rules)
    assert proj["entry"] == 3400.0
    assert proj["stop"] is not None and proj["stop"] < 3400.0
    assert proj["target"] is not None and proj["target"] > 3400.0
    # 1.2 * 100 = 120 stop dist; target = 3400 + 1.5*120 = 3580
    assert abs(float(proj["stop"]) - 3280.0) < 1e-6
    assert abs(float(proj["target"]) - 3580.0) < 1e-6

    row = build_final_signal_row(
        tmp_path,
        "MA",
        report={"signals": [sig]},
        sentiment={"direction": "多", "conviction_pct": 45, "label": "多 · 把握 45%"},
        book={"ok": True, "positions": {}},
        decision_or_none={"结论": "偏多", "把握": "中"},
        regime_key="trend",
        sig=sig,
        name="甲醇",
        rules=rules,
    )
    assert row["最终动作"] == "建议开"
    assert row["止损"] is not None
    assert row["止盈"] is not None
    assert abs(float(row["止损"]) - 3280.0) < 1e-6
    assert abs(float(row["止盈"]) - 3580.0) < 1e-6


def test_row_stop_alert_from_paper_book(tmp_path: Path):
    book = {
        "ok": True,
        "positions": {
            "V": {
                "code": "V",
                "direction": "多",
                "lots": 1,
                "entry": 4800.0,
                "stop": 4700.0,
                "target": 5100.0,
                "atr": 120.0,
                "mark": 4650.0,
                "equity_delta": -750.0,
            }
        },
    }
    row = build_final_signal_row(
        tmp_path,
        "V",
        report={"signals": []},
        sentiment={"direction": "多", "conviction_pct": 30, "label": "多 · 把握 30%"},
        book=book,
        decision_or_none={"结论": "偏多", "把握": "高"},
        regime_key="mixed",
        name="PVC",
    )
    assert row["最终动作"] == "止损预警"
    assert row["模拟仓"].startswith("多")


def test_board_primary_is_held_union_selected_directed(tmp_path: Path):
    (tmp_path / "execution_rules.json").write_text(
        '{"ok": true, "stop_atr_mult": 1.2, "reward_rr": 1.5}',
        encoding="utf-8",
    )
    (tmp_path / "universe.json").write_text(
        '{"symbols": [{"code": "MA", "name": "甲醇"}, {"code": "CF", "name": "棉花"},'
        '{"code": "AU", "name": "黄金"}]}',
        encoding="utf-8",
    )
    report = {
        "asof": "20261028",
        "signals": [
            {
                "code": "MA",
                "name": "甲醇",
                "direction": "多",
                "selected": True,
                "lots_l1": 1,
                "close": 3400.0,
                "atr": 100.0,
            },
            {
                "code": "CF",
                "name": "棉花",
                "direction": "空",
                "selected": False,
                "lots_l1": 0,
                "close": 15000.0,
                "atr": 200.0,
            },
            {
                "code": "AU",
                "name": "黄金",
                "direction": "震荡",
                "selected": False,
                "lots_l1": 0,
                "close": 500.0,
                "atr": 5.0,
            },
        ],
    }
    book = {
        "ok": True,
        "end": "2026-10-28",
        "positions": {
            "FG": {
                "code": "FG",
                "direction": "空",
                "lots": 2,
                "entry": 844.0,
                "stop": 870.0,
                "target": 810.0,
                "atr": 16.0,
                "mark": 840.0,
                "equity_delta": 80.0,
            }
        },
    }
    decisions = {
        "MA": {"结论": "偏多", "把握": "中"},
        "CF": {"结论": "观望", "把握": "低"},
        "FG": {"结论": "偏空", "把握": "高"},
        "AU": {"结论": "观望", "把握": "低"},
    }
    board = build_final_signal_board(
        tmp_path,
        report=report,
        book=book,
        sentiment_snap={
            "stance": "neutral",
            "portfolio_p3": 0.05,
            "longs": [],
            "shorts": [],
        },
        regime_key="mixed",
        decisions=decisions,
        compute_decisions=False,
    )
    primary_codes = {r["代码"] for r in board["primary"]}
    # held FG ∪ selected MA ∪ directed CF (空)
    assert "FG" in primary_codes
    assert "MA" in primary_codes
    assert "CF" in primary_codes
    assert "AU" not in primary_codes or any(
        r["代码"] == "AU" for r in board["other"]
    )
    ma = next(r for r in board["primary"] if r["代码"] == "MA")
    assert ma["最终动作"] == "建议开"
    fg = next(r for r in board["primary"] if r["代码"] == "FG")
    assert fg["最终动作"] == "持有"
    assert board["live_trading"] is False


def test_row_mismatch_l1_vs_decision_not_open(tmp_path: Path):
    rules = {"stop_atr_mult": 1.2, "reward_rr": 1.5}
    (tmp_path / "execution_rules.json").write_text(
        '{"ok": true, "stop_atr_mult": 1.2, "reward_rr": 1.5}',
        encoding="utf-8",
    )
    sig = {
        "code": "MA",
        "name": "甲醇",
        "direction": "空",
        "selected": True,
        "lots_l1": 2,
        "close": 3400.0,
        "atr": 100.0,
    }
    row = build_final_signal_row(
        tmp_path,
        "MA",
        report={"signals": [sig]},
        sentiment={"direction": "多", "conviction_pct": 45, "label": "多 · 把握 45%"},
        book={"ok": True, "positions": {}},
        decision_or_none={"结论": "偏多", "把握": "中"},
        regime_key="trend",
        sig=sig,
        name="甲醇",
        rules=rules,
    )
    assert row["最终动作"] != "建议开"
    assert row["最终动作"] == "观望"
    assert "不一致" in str(row.get("_primary_tip") or "")


def test_row_decision_unavailable_held_not_suggest_close(tmp_path: Path):
    book = {
        "ok": True,
        "positions": {
            "V": {
                "code": "V",
                "direction": "多",
                "lots": 1,
                "entry": 4800.0,
                "stop": 4700.0,
                "target": 5100.0,
                "atr": 120.0,
                "mark": 4850.0,
                "equity_delta": 50.0,
            }
        },
    }
    row = build_final_signal_row(
        tmp_path,
        "V",
        report={"signals": []},
        sentiment={"direction": "多", "conviction_pct": 30, "label": "多 · 把握 30%"},
        book=book,
        decision_or_none={
            "结论": "观望",
            "把握": "低",
            "理由": "决策不可用：boom",
            "_unavailable": True,
        },
        regime_key="mixed",
        name="PVC",
    )
    assert row["最终动作"] == "观望"
    assert "决策不可用" in str(row.get("_primary_tip") or row.get("理由") or "")


def test_infer_desk_regime_from_decisions_smoke(tmp_path: Path):
    (tmp_path / "regime_enable.json").write_text(
        Path(__file__).resolve().parents[1].joinpath("regime_enable.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    key = infer_desk_regime_key(
        root=tmp_path,
        report={"signals": []},
        decisions={
            "MA": {"结论": "偏多", "把握": "中", "领先方向": "多"},
            "FG": {"结论": "偏空", "把握": "高", "领先方向": "空"},
        },
        sentiment={"direction": "多", "conviction_pct": 40},
    )
    assert key == "trend"

    chop_key = infer_desk_regime_key(
        root=tmp_path,
        report={"signals": []},
        decisions={
            "AU": {"结论": "观望", "把握": "低"},
            "CF": {"结论": "观望", "把握": "低"},
        },
        sentiment={"direction": "震荡", "conviction_pct": 20},
    )
    assert chop_key == "chop"

    # No desk crumbs → mixed (not config default alone as sole signal)
    empty = infer_desk_regime_key(
        root=tmp_path,
        report={"signals": []},
        decisions={},
        sentiment=None,
    )
    assert empty == "mixed"
