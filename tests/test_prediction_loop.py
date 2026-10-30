# -*- coding: utf-8 -*-
"""P0 prediction log + attribution unit tests."""
from __future__ import annotations

import json
from pathlib import Path

from prediction_log import conclusion_to_direction, rows_to_predictions, write_desk_predictions
from prediction_score import classify_outcome, forward_return, score_prediction, summarize


def test_conclusion_to_direction():
    assert conclusion_to_direction("偏多研究") == "多"
    assert conclusion_to_direction("偏空研究") == "空"
    assert conclusion_to_direction("观望") == "观望"
    assert conclusion_to_direction("波动率卖方研究") == "观望"


def test_classify_outcome():
    assert classify_outcome("多", 0.01) == "命中"
    assert classify_outcome("多", -0.01) == "方向错误"
    assert classify_outcome("空", -0.02) == "命中"
    assert classify_outcome("空", 0.02) == "方向错误"
    assert classify_outcome("观望", 0.01) == "无法判断"
    assert classify_outcome("多", None) == "无法判断"
    assert classify_outcome("多", 0.0) == "无法判断"


def test_forward_return_horizon(tmp_path: Path):
    bars = [
        ("2026-10-20", 100.0),
        ("2026-10-21", 101.0),
        ("2026-10-22", 102.0),
        ("2026-10-23", 99.0),
        ("2026-10-24", 98.0),
    ]
    r1 = forward_return(bars, "20261020", 1)
    assert r1["ok"] is True
    assert abs(r1["ret"] - 0.01) < 1e-9
    r3 = forward_return(bars, "2026-10-20", 3)
    assert r3["ok"] is True
    assert abs(r3["ret"] - (-0.01)) < 1e-9
    pending = forward_return(bars, "20261023", 5)
    assert pending["ok"] is False
    assert pending["error"] == "horizon_pending"


def test_score_prediction_and_summary(tmp_path: Path):
    root = tmp_path
    bars_dir = root / "lab" / "data" / "bars" / "continuous"
    bars_dir.mkdir(parents=True)
    (bars_dir / "CF.json").write_text(
        json.dumps(
            {
                "code": "CF",
                "bars": [
                    {"date": "2026-10-20", "close": 100.0},
                    {"date": "2026-10-21", "close": 103.0},
                    {"date": "2026-10-22", "close": 104.0},
                    {"date": "2026-10-23", "close": 105.0},
                    {"date": "2026-10-24", "close": 106.0},
                    {"date": "2026-10-27", "close": 107.0},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pred = {
        "id": "PRED-20261020-CF",
        "asof": "20261020",
        "code": "CF",
        "direction": "多",
        "horizons": [1, 3, 5],
        "scores": {
            "1": {"status": "pending", "horizon_days": 1},
            "3": {"status": "pending", "horizon_days": 3},
            "5": {"status": "pending", "horizon_days": 5},
        },
    }
    scored = score_prediction(pred, root=root)
    assert scored["scores"]["1"]["status"] == "scored"
    assert scored["scores"]["1"]["class"] == "命中"
    assert scored["scores"]["3"]["class"] == "命中"
    assert scored["scores"]["5"]["class"] == "命中"
    summ = summarize([scored])
    assert summ["hits"] == 3
    assert summ["hit_rate"] == 1.0


def test_rows_to_predictions_ids():
    board = {
        "asof": "20261029",
        "conviction_pct": 55.0,
        "rows": [
            {
                "code": "CF",
                "path_a": "空",
                "sentiment": "多",
                "align": "冲突",
                "vol": "观望",
                "conclusion": "观望",
                "note": "冲突",
            }
        ],
    }
    preds = rows_to_predictions(board, root=Path("."))
    assert len(preds) == 1
    assert preds[0]["id"] == "PRED-20261029-CF"
    assert preds[0]["direction"] == "观望"
    assert "1" in preds[0]["scores"]


def test_write_desk_predictions_smoke():
    """Live smoke against repo sentiment/vol if present; else skip soft."""
    root = Path(__file__).resolve().parents[1]
    sent = root / "data" / "sentiment_mds" / "latest.json"
    if not sent.is_file():
        return
    out = write_desk_predictions(root)
    assert out.get("ok") is True
    assert int(out.get("n") or 0) >= 1
    latest = root / "lab" / "research" / "predictions" / "latest.json"
    assert latest.is_file()
