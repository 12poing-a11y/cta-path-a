# -*- coding: utf-8 -*-
"""Paper-book equity helpers for the research desk (display only for mark)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from desk.loaders import load_json


def load_book_equity(root: Path, report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prefer paper_book_latest mark/equity; fall back to l1 report fields."""
    paper = load_json(root / "paper_book_latest.json") or {}
    report = report or load_json(root / "l1_report_risk15.json") or load_json(root / "l1_report.json") or {}
    if paper.get("ok") and paper.get("equity") is not None:
        equity = float(paper.get("equity") or 0)
        floating = float(paper.get("equity_floating") or 0)
        mark = float(paper.get("equity_mark") or (equity + floating))
        return {
            "ok": True,
            "source": "paper_book",
            "asof": paper.get("asof") or report.get("paper_asof") or report.get("asof"),
            "equity": round(equity, 2),
            "equity_floating": round(floating, 2),
            "equity_mark": round(mark, 2),
            "held_n": paper.get("held_n") or len(paper.get("positions") or {}),
        }
    equity = report.get("equity")
    if equity is not None:
        floating = float(report.get("equity_floating") or 0)
        mark = float(report.get("equity_mark") or (float(equity) + floating))
        return {
            "ok": True,
            "source": str(report.get("equity_source") or "l1_report"),
            "asof": report.get("paper_asof") or report.get("asof"),
            "equity": round(float(equity), 2),
            "equity_floating": round(floating, 2),
            "equity_mark": round(mark, 2),
            "held_n": None,
        }
    return {
        "ok": False,
        "source": "none",
        "asof": None,
        "equity": None,
        "equity_floating": None,
        "equity_mark": None,
        "held_n": None,
    }
