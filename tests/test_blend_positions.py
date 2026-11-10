# -*- coding: utf-8 -*-
"""Blended holdings reference from A capital weights."""
from __future__ import annotations

import json
from pathlib import Path

from desk.blend_positions import (
    OBSERVE_CAP,
    OBSERVE_ID,
    build_blend_holdings,
    holdings_df,
    load_best_blend_weights,
)

ROOT = Path(__file__).resolve().parents[1]


def test_scale_and_aggregate_with_explicit_weights(tmp_path):
    # Path-A paper book
    book = {
        "ok": True,
        "asof": "2026-11-10",
        "source": "test",
        "positions": {
            "MA": {
                "code": "MA",
                "name": "甲醇",
                "direction": "多",
                "lots": 2,
                "entry": 3000,
                "mark": 3000,
                "mult": 10,
                "entry_date": "2026-11-01",
            }
        },
    }
    (tmp_path / "paper_book_latest.json").write_text(json.dumps(book), encoding="utf-8")
    # Observe sleeve shares MA long + adds short L
    obs = {
        "name": "观察袖套",
        "end": "2026-11-09",
        "positions_asof": "2026-11-09",
        "final_positions": [
            {
                "code": "MA",
                "name": "甲醇",
                "direction": "long",
                "lots_equiv": 1.0,
                "notional_yuan": 1000,
                "entry_date": "2026-10-01",
            },
            {
                "code": "L",
                "name": "塑料",
                "direction": "short",
                "lots_equiv": 2.0,
                "notional_yuan": 2000,
                "entry_date": "2026-10-02",
            },
        ],
    }
    d = tmp_path / "external" / "strategies"
    d.mkdir(parents=True)
    (d / f"{OBSERVE_ID}.json").write_text(json.dumps(obs), encoding="utf-8")

    # Stub load_paper_book via paper_book module path used by decision
    # decision.load_paper_book tries paper_book.load_paper_positions first
    import paper_book

    orig = getattr(paper_book, "load_paper_positions", None)

    def _load(_root):
        return book

    paper_book.load_paper_positions = _load  # type: ignore
    try:
        pack = build_blend_holdings(
            tmp_path,
            weights={"path_a": 0.9, OBSERVE_ID: 0.1},
            blend_meta={"label": "测试 90/10", "calmar": 1.2, "blend_asof": "t"},
        )
    finally:
        if orig is not None:
            paper_book.load_paper_positions = orig  # type: ignore

    assert pack["ok"]
    by = {(r["code"], r["direction"]): r for r in pack["rows"]}
    # MA 多: 2*0.9 + 1*0.1 = 1.9 (≥1, unchanged)
    assert abs(by[("MA", "多")]["lots_ref"] - 1.9) < 1e-6
    assert set(by[("MA", "多")]["sleeve_ids"]) == {"path_a", OBSERVE_ID}
    # L 空: 2*0.1 = 0.2 → floor to 1 手
    assert abs(by[("L", "空")]["lots_raw"] - 0.2) < 1e-6
    assert by[("L", "空")]["lots_ref"] == 1.0
    assert by[("L", "空")]["lots_floored"] is True
    df = holdings_df(pack, root=None)
    assert {"品种", "方向", "参考手数", "来源袖套"} <= set(df.columns)


def test_observe_over_cap_weights_rejected_from_artifact(tmp_path):
    payload = {
        "best_by_calmar": [{"blend_id": "bad", "label": "坏", "weights_zh": "x"}],
        "rows": [
            {
                "blend_id": "bad",
                "ok": True,
                "weights": {OBSERVE_ID: OBSERVE_CAP + 0.05, "path_a": 0.85},
            }
        ],
    }
    p = tmp_path / "data" / "ablation"
    p.mkdir(parents=True)
    (p / "strategy_blend_latest.json").write_text(json.dumps(payload), encoding="utf-8")
    assert load_best_blend_weights(tmp_path) is None


def test_repo_best_blend_holdings_soft():
    meta = load_best_blend_weights(ROOT)
    if meta is None:
        return
    assert float(meta["weights"].get(OBSERVE_ID) or 0) <= OBSERVE_CAP + 1e-9
    pack = build_blend_holdings(ROOT)
    assert pack["ok"]
    assert pack["n_legs"] >= 0
    if pack["rows"]:
        df = holdings_df(pack, root=ROOT)
        assert "参考手数" in df.columns
