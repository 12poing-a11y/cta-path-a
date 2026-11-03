# -*- coding: utf-8 -*-
"""Local research desk kept its pages, and chart sync shows the last bar."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd

from desk.chart_board import format_last_daily_bar_caption, last_bar_timestamp
from desk.equity_book import load_book_equity
from desk.sentiment_panel import load_sentiment_snapshot
from desk.sync_desk import sync_desk

ROOT = Path(__file__).resolve().parents[1]


def _assign_str_tuple(path: Path, name: str) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"{name} missing in {path}")


def test_radio_pages_keep_local_nav():
    pages = _assign_str_tuple(ROOT / "desk" / "app.py", "DESK_PAGES")
    assert pages[0] == "最终信号"
    assert "情绪" in pages
    assert "状态评分" in pages
    assert "图表" in pages
    # Radio nav, not the thinner main-tab shell.
    app = (ROOT / "desk" / "app.py").read_text(encoding="utf-8")
    assert 'st.radio(\n        "页面"' in app
    assert "同步 main 日报 + 图表行情缓存（日线 CODE0 / 15m / 60m）" in app


def test_sentiment_panel_prefers_shadow(tmp_path: Path):
    text = (ROOT / "desk" / "sentiment_panel.py").read_text(encoding="utf-8")
    assert len(text) > 12000
    assert "def load_sentiment_snapshot" in text
    assert "_newest_shadow" in text
    shadow = tmp_path / "data" / "sentiment_mds" / "shadow"
    shadow.mkdir(parents=True)
    (shadow / "sentiment_20261101.json").write_text(
        json.dumps({"asof": "20261101", "portfolio_p3": 0.2, "stance": "risk_on"}),
        encoding="utf-8",
    )
    formal = tmp_path / "data" / "sentiment_mds"
    (formal / "latest.json").write_text(
        json.dumps({"asof": "20261103", "portfolio_p3": -0.9, "stance": "risk_off"}),
        encoding="utf-8",
    )
    snap = load_sentiment_snapshot(tmp_path)
    assert snap is not None
    assert snap["asof"] == "20261101"
    assert snap.get("shadow") is True
    assert snap["_source_path"] == "sentiment_20261101.json"


def test_daily_update_does_not_overwrite_formal_sentiment_latest():
    text = (ROOT / "daily_update.py").read_text(encoding="utf-8")
    assert "update_latest=False" in text
    assert '_SENT_OUT / "shadow"' in text
    assert "禁止改正式 latest.json" in text


def test_sync_desk_checks_out_chart_caches():
    text = (ROOT / "desk" / "sync_desk.py").read_text(encoding="utf-8")
    # Planned step and the real checkout list both name the chart caches.
    assert text.count(".cache/sina") >= 2
    assert text.count(".cache/akshare/minute") >= 2
    planned = sync_desk(ROOT, pull_git=True, refresh_cache=False, dry_run=True)
    detail = " ".join(str(step.get("detail") or "") for step in planned["steps"])
    assert ".cache/sina" in detail
    assert ".cache/akshare/minute" in detail
    assert planned["ok"] is True


def test_last_bar_captions():
    bars = [
        {"datetime": "2026-11-03 09:00:00", "date": "2026-11-03"},
        {"datetime": "2026-11-03 14:45:00", "date": "2026-11-03"},
    ]
    assert last_bar_timestamp(bars) == "2026-11-03 14:45:00"
    assert last_bar_timestamp([]) == ""
    assert last_bar_timestamp([{"date": "2026-11-02"}]) == "2026-11-02"
    daily = pd.DataFrame({"date": ["2026-11-01", "2026-11-03"]})
    caption = format_last_daily_bar_caption(daily)
    assert "2026-11-03" in caption
    assert "最后一根K线" in caption
    assert "同步 main 行情缓存" in caption
    empty_cap = format_last_daily_bar_caption(daily.iloc[0:0])
    assert "最后一根K线：—" in empty_cap
    assert "同步 main 行情缓存" in empty_cap


def test_equity_book_is_display_only(tmp_path: Path):
    (tmp_path / "paper_book_latest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "asof": "20261103",
                "equity": 1000,
                "equity_floating": 25,
                "equity_mark": 1025,
                "positions": {"CF": {}},
            }
        ),
        encoding="utf-8",
    )
    book = load_book_equity(tmp_path, {"asof": "20261102", "equity": 1})
    assert book["ok"] is True
    assert book["source"] == "paper_book"
    assert book["equity_mark"] == 1025.0
    assert book["held_n"] == 1
