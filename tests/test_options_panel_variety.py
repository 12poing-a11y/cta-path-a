# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from desk.options_panel import build_opportunities, paper_holdings_table


def test_paper_holdings_shows_variety_label(tmp_path: Path):
    uni = {
        "symbols": [{"code": "CF", "name": "棉花", "mult": 5, "exchange": "CZCE"}],
        "observe": {"option_hedge": {"premium_atr_mult": 0.35, "strike_atr_mult": 1.0}},
    }
    (tmp_path / "universe.json").write_text(json.dumps(uni), encoding="utf-8")
    paper = {
        "ok": True,
        "asof": "2026-11-12",
        "positions": {
            "CF": {
                "direction": "空",
                "lots": 2,
                "entry": 15000,
                "stop": 15200,
                "target": 14600,
                "atr": 120,
                "entry_date": "2026-11-10",
                "name": "棉花",
            }
        },
        "trade_ledger": [],
    }
    (tmp_path / "paper_book_latest.json").write_text(json.dumps(paper), encoding="utf-8")
    (tmp_path / "l1_report.json").write_text(
        json.dumps({"asof": "20261112", "signals": [], "portfolio": {"selected": []}}),
        encoding="utf-8",
    )
    held = paper_holdings_table(tmp_path)
    assert not held.empty
    assert "棉花" in str(held.iloc[0]["品种"])
    assert held.iloc[0]["代码"] == "CF"


def test_opportunities_observe_fallback_has_variety(tmp_path: Path):
    uni = {
        "symbols": [{"code": "MA", "name": "甲醇", "mult": 10, "exchange": "CZCE"}],
        "observe": {"option_hedge": {"premium_atr_mult": 0.35, "strike_atr_mult": 1.0}},
    }
    (tmp_path / "universe.json").write_text(json.dumps(uni), encoding="utf-8")
    (tmp_path / "paper_book_latest.json").write_text(
        json.dumps({"ok": True, "asof": "2026-11-12", "positions": {}, "trade_ledger": []}),
        encoding="utf-8",
    )
    (tmp_path / "l1_report.json").write_text(
        json.dumps(
            {
                "asof": "20261112",
                "l1_risk_yuan": 3000,
                "signals": [
                    {
                        "code": "MA",
                        "name": "甲醇",
                        "direction": "多",
                        "lots_l1": 0,
                        "close": 2500,
                        "atr": 40,
                        "mult": 10,
                    }
                ],
                "portfolio": {"selected": []},
            }
        ),
        encoding="utf-8",
    )
    opp = build_opportunities(root=tmp_path)
    assert not opp.empty
    assert "甲醇" in str(opp.iloc[0]["品种"])
    assert opp.iloc[0]["代码"] == "MA"
    assert opp.attrs.get("book_source") == "l1_observe"
