# -*- coding: utf-8 -*-
"""Shadow metrics and evaluation hooks that this slice does not claim to finish.

Trade summaries describe one simulation. They are not a promotion decision.
Ablation and walk-forward return an explicit stub so a report cannot show a
blank field and be read as a pass.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from signals.order_block_sim import ShadowTrade

# Formal Path-A artifacts this track must not overwrite.
FORMAL_ARTIFACTS = (
    "execution_rules.json",
    "universe.json",
    "paper_book_latest.json",
    "l1_report.json",
    "historical_backtest_latest.json",
    "benchmark_latest.json",
    "param_sweep_latest.json",
    "weekly_backtest_latest.json",
)


def summarize_trades(trades: list[ShadowTrade]) -> dict[str, Any]:
    """Describe realized R multiples. An empty book is a valid result."""
    note = (
        "Shadow diagnostics for a zone-boundary stop. "
        "Not a claim of edge and not a Path-A result."
    )
    if not trades:
        return {
            "trade_count": 0,
            "win_rate": None,
            "avg_win_r": None,
            "avg_loss_r": None,
            "expectancy_r": None,
            "profit_factor": None,
            "max_consecutive_losses": 0,
            "note": note,
        }
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    streak = 0
    worst = 0
    for r in rs:
        if r <= 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(trades),
        "win_rate": len(wins) / len(rs),
        "avg_win_r": (sum(wins) / len(wins)) if wins else None,
        "avg_loss_r": (sum(losses) / len(losses)) if losses else None,
        "expectancy_r": sum(rs) / len(rs),
        "profit_factor": (gross_win / gross_loss) if gross_loss else None,
        "max_consecutive_losses": worst,
        "note": note,
    }


def ablation_plan() -> dict[str, Any]:
    """Hook for a later equal-risk comparison. It does not run one."""
    return {
        "status": "stub",
        "hook": "signals.order_block_eval.ablation_plan",
        "question": (
            "Under the same bars, costs, and risk budget, does an order-block "
            "location change results relative to the same execution without it?"
        ),
        "measured": False,
        "not_a_result": True,
    }


def walk_forward_plan() -> dict[str, Any]:
    """Hook for a later rolling window. Parameters stay the baseline defaults."""
    return {
        "status": "stub",
        "hook": "signals.order_block_eval.walk_forward_plan",
        "measured": False,
        "not_a_result": True,
        "note": (
            "baseline.json values are fixed research defaults. "
            "They were not selected on a test window."
        ),
    }


def assert_shadow_destination(root: Path, path: Path) -> Path:
    """Allow a shadow file under data/order_block/shadow, or a path outside the repo.

    Refuses formal latest names and any other in-repo destination.
    """
    root_r = root.resolve()
    dest = path.resolve()
    if dest.name in FORMAL_ARTIFACTS or dest.name == "latest.json":
        raise ValueError(f"refusing to write formal artifact name {dest.name}")
    shadow_root = (root_r / "data" / "order_block" / "shadow").resolve()
    try:
        dest.relative_to(shadow_root)
        return dest
    except ValueError:
        pass
    try:
        dest.relative_to(root_r)
    except ValueError:
        return dest
    raise ValueError(
        "shadow output inside the repo must stay under data/order_block/shadow"
    )
