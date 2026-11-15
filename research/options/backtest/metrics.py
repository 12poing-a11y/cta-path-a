# -*- coding: utf-8 -*-
"""Aggregate KPIs for credit-vertical research trades."""
from __future__ import annotations

from typing import Any


def summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if t.get("status") == "closed"]
    n = len(closed)
    if n == 0:
        return {
            "n_closed": 0,
            "n_skipped": sum(1 for t in trades if t.get("status") == "skipped"),
            "win_rate": None,
            "avg_credit_points": None,
            "avg_pnl_points": None,
            "avg_pnl_cny": None,
            "max_adverse_points": None,
            "total_pnl_cny": 0.0,
            "sum_margin_est_cny": 0.0,
        }
    wins = sum(1 for t in closed if float(t.get("pnl_points") or 0) > 0)
    pnls = [float(t.get("pnl_points") or 0) for t in closed]
    credits = [float(t.get("credit_points") or 0) for t in closed]
    pnls_cny = [float(t.get("pnl_cny") or 0) for t in closed]
    adverse = [float(t.get("max_adverse_points") or 0) for t in closed]
    margins = [float(t.get("margin_est_cny") or 0) for t in closed]
    return {
        "n_closed": n,
        "n_skipped": sum(1 for t in trades if t.get("status") == "skipped"),
        "win_rate": round(wins / n, 4),
        "avg_credit_points": round(sum(credits) / n, 4),
        "avg_pnl_points": round(sum(pnls) / n, 4),
        "avg_pnl_cny": round(sum(pnls_cny) / n, 2),
        "max_adverse_points": round(max(adverse) if adverse else 0.0, 4),
        "total_pnl_cny": round(sum(pnls_cny), 2),
        "sum_margin_est_cny": round(sum(margins), 2),
    }
