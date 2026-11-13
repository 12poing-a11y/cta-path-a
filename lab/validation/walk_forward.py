# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Sequence

from lab.validation.returns import moments


def walk_forward_segments(
    returns: Sequence[float],
    *,
    n_folds: int = 5,
    min_bars: int = 20,
) -> dict[str, Any]:
    """Simple expanding/rolling fold Sharpe table (not a full WF optimizer)."""
    xs = [float(x) for x in returns]
    n = len(xs)
    if n < max(min_bars * 2, n_folds * min_bars):
        return {"ok": False, "error": "insufficient_sample", "n": n, "folds": []}
    fold_size = n // n_folds
    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = n if i == n_folds - 1 else (i + 1) * fold_size
        chunk = xs[start:end]
        if len(chunk) < min_bars:
            continue
        m = moments(chunk)
        folds.append(
            {
                "fold": i + 1,
                "start_i": start,
                "end_i": end,
                "n": m["n"],
                "sharpe": None if m["sharpe"] is None else round(float(m["sharpe"]), 4),
                "mean": None if m["mean"] is None else round(float(m["mean"]), 6),
            }
        )
    sharpes = [f["sharpe"] for f in folds if f.get("sharpe") is not None]
    pos = sum(1 for s in sharpes if s > 0)
    return {
        "ok": True,
        "n": n,
        "n_folds": len(folds),
        "folds": folds,
        "positive_fold_share": round(pos / len(sharpes), 4) if sharpes else None,
        "note": "Fold Sharpes for stability glance; not a substitute for locked OOS.",
    }
