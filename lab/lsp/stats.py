# -*- coding: utf-8 -*-
"""Conditional probability tables for LSP outcomes."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Sequence


def summarize_events(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    rows = [e for e in events if e.get("outcome")]
    n = len(rows)
    counts = Counter(e["outcome"] for e in rows)
    by_dir = defaultdict(Counter)
    by_tf = defaultdict(Counter)
    for e in rows:
        by_dir[str(e.get("break_direction"))][e["outcome"]] += 1
        by_tf[str(e.get("timeframe"))][e["outcome"]] += 1

    def _probs(counter: Counter) -> dict[str, float]:
        tot = sum(counter.values()) or 1
        return {k: round(v / tot, 4) for k, v in sorted(counter.items())}

    # Volume regime split
    high_vol = [e for e in rows if (e.get("volume_ratio") or 0) >= 1.2]
    low_vol = [e for e in rows if (e.get("volume_ratio") or 0) < 1.2]
    mfe_vals = [float(e["mfe"]) for e in rows if e.get("mfe") is not None]
    mae_vals = [float(e["mae"]) for e in rows if e.get("mae") is not None]

    def _avg(xs: list[float]) -> float | None:
        return None if not xs else round(sum(xs) / len(xs), 4)

    return {
        "schema": "cta-lsp-stats-v1",
        "n_events": n,
        "outcome_counts": dict(counts),
        "outcome_probs": _probs(counts),
        "by_direction": {k: _probs(v) for k, v in by_dir.items()},
        "by_timeframe": {k: _probs(v) for k, v in by_tf.items()},
        "high_volume_ge_1_2": {
            "n": len(high_vol),
            "probs": _probs(Counter(e["outcome"] for e in high_vol)),
        },
        "low_volume_lt_1_2": {
            "n": len(low_vol),
            "probs": _probs(Counter(e["outcome"] for e in low_vol)),
        },
        "avg_mfe_atr": _avg(mfe_vals),
        "avg_mae_atr": _avg(mae_vals),
        "live_trading": False,
        "status": "Research",
        "note": "Conditional frequencies only; not Path-A entry rules.",
    }
