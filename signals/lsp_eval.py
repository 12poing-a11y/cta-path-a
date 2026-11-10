# -*- coding: utf-8 -*-
"""LSP shadow destination guards (mirror order_block_eval)."""
from __future__ import annotations

from pathlib import Path

FORMAL_ARTIFACTS = frozenset(
    {
        "paper_book_latest.json",
        "l1_report.json",
        "historical_backtest_latest.json",
        "benchmark_latest.json",
        "strategy_blend_latest.json",
    }
)


def assert_shadow_destination(root: Path, path: Path) -> Path:
    """Shadow output must stay under data/lsp/shadow (or outside the repo)."""
    root_r = root.resolve()
    dest = path.resolve()
    if dest.name in FORMAL_ARTIFACTS or dest.name == "latest.json":
        raise ValueError(f"refusing to write formal artifact name {dest.name}")
    shadow_root = (root_r / "data" / "lsp" / "shadow").resolve()
    try:
        dest.relative_to(shadow_root)
        return dest
    except ValueError:
        pass
    try:
        dest.relative_to(root_r)
    except ValueError:
        return dest
    raise ValueError("shadow output inside the repo must stay under data/lsp/shadow")
