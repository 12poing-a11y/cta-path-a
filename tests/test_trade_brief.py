# -*- coding: utf-8 -*-
"""Trade-referable Notion brief builder (no network)."""
from __future__ import annotations

import json
from pathlib import Path

import notion_sync


def test_build_trade_brief_filters_actionable(tmp_path: Path, monkeypatch):
    report = {
        "asof": "20261113",
        "signals": [
            {
                "code": "P",
                "name": "棕榈油",
                "direction": "空",
                "lots_l1": 1,
                "selected": True,
                "action": "路径A记账",
                "close": 9000,
                "atr": 100,
            },
            {
                "code": "MA",
                "name": "甲醇",
                "direction": "多",
                "lots_l1": 0,
                "selected": False,
                "action": "空仓",
            },
        ],
    }
    (tmp_path / "l1_report_risk15.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "universe.json").write_text(
        json.dumps({"symbols": [{"code": "P", "name": "棕榈油"}, {"code": "MA", "name": "甲醇"}]}),
        encoding="utf-8",
    )
    (tmp_path / "execution_rules.json").write_text("{}", encoding="utf-8")
    (tmp_path / "paper_book_latest.json").write_text(
        json.dumps({"ok": True, "positions": {}, "asof": "2026-11-13"}),
        encoding="utf-8",
    )

    fake_board = {
        "ok": True,
        "asof": "20261113",
        "regime": "偏空",
        "sentiment": {"direction": "空", "conviction_pct": 40},
        "metrics": {"open_n": 1, "held_n": 0, "alert_n": 0},
        "primary": [
            {
                "代码": "P",
                "品种": "P2701 棕榈油",
                "最终动作": "建议开",
                "方向": "空",
                "手数": 1,
                "入场": 9000,
                "止损": 9100,
                "止盈": 8800,
                "_primary_tip": "日选与决策同向",
                "_l1_selected": True,
            },
            {
                "代码": "MA",
                "品种": "MA2701 甲醇",
                "最终动作": "观望",
                "方向": "多",
                "手数": 0,
                "_l1_selected": False,
            },
        ],
        "other": [],
    }
    monkeypatch.setattr(
        "desk.final_signal.build_final_signal_board",
        lambda *a, **k: fake_board,
    )
    monkeypatch.setattr("desk.final_signal.FOOTER", "研究建议，非交易指令。", raising=False)

    brief = notion_sync.build_trade_brief(tmp_path, report=report)
    assert brief["ok"] is True
    assert brief["date"] == "2026-11-13"
    assert [r["code"] for r in brief["rows"]] == ["P"]
    assert brief["rows"][0]["action"] == "建议开"
    assert "止损9100" in brief["rows"][0]["line"]
    saved = json.loads((tmp_path / "data" / "trade_brief_latest.json").read_text(encoding="utf-8"))
    assert saved["metrics"]["brief_n"] == 1


def test_sync_trade_brief_posts_page(monkeypatch, tmp_path: Path):
    brief = {
        "ok": True,
        "date": "2026-11-13",
        "asof": "20261113",
        "regime": "偏空",
        "sentiment": {"direction": "空", "conviction_pct": 40},
        "metrics": {"brief_n": 1, "open_n": 1, "held_n": 0, "alert_n": 0},
        "rows": [
            {
                "code": "P",
                "action": "建议开",
                "line": "P2701 棕榈油｜建议开｜空｜1手",
            }
        ],
        "disclaimer": "研究建议，非交易指令。",
    }
    monkeypatch.setattr(notion_sync, "build_trade_brief", lambda *a, **k: brief)
    monkeypatch.setattr(notion_sync, "_headers", lambda: {"Authorization": "Bearer x"})
    posts = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "page-1"}

    def fake_post(url, headers=None, json=None, timeout=60):
        posts.append({"url": url, "json": json})
        return _Resp()

    monkeypatch.setattr(notion_sync.requests, "post", fake_post)
    assert notion_sync.sync_trade_brief(root=tmp_path) == 0
    assert posts and "pages" in posts[0]["url"]
    title = posts[0]["json"]["properties"]["title"][0]["text"]["content"]
    assert title.startswith("2026-11-13 交易参照")
