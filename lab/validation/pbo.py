# -*- coding: utf-8 -*-
"""Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation."""
from __future__ import annotations

import itertools
import math
from typing import Any, Sequence

from lab.validation.returns import moments


def _sharpe_col(col: Sequence[float], periods_per_year: float = 252.0) -> float:
    m = moments(col)
    sh = m["sharpe"]
    return float(sh) if sh is not None else float("-inf")


def probability_of_backtest_overfitting(
    returns_matrix: Sequence[Sequence[float]],
    *,
    n_groups: int = 16,
    periods_per_year: float = 252.0,
    max_combos: int = 5000,
) -> dict[str, Any]:
    """PBO from a T×K matrix (rows=time, cols=strategy trials).

    CSCV: split time into S even chunks; for each combination of S/2 chunks as IS,
    pick best-IS strategy by Sharpe, then check if its OOS rank is below median.
    PBO ≈ share of combos where the IS winner underperforms OOS median.
    """
    if not returns_matrix or not returns_matrix[0]:
        return {"ok": False, "pbo": None, "error": "empty_matrix"}
    t = len(returns_matrix)
    k = len(returns_matrix[0])
    if k < 2:
        return {
            "ok": False,
            "pbo": None,
            "error": "need_at_least_2_trials",
            "n_trials": k,
            "note": "Single-strategy Path-A cannot estimate PBO without a trial matrix.",
        }
    s = int(n_groups)
    if s < 2 or s % 2 != 0:
        return {"ok": False, "pbo": None, "error": "n_groups_must_be_even_ge_2"}
    if t < s * 2:
        return {"ok": False, "pbo": None, "error": "series_too_short", "n": t, "n_groups": s}

    # Trim to multiple of S
    usable = (t // s) * s
    data = [list(map(float, returns_matrix[i])) for i in range(usable)]
    chunk = usable // s
    groups = [data[i * chunk : (i + 1) * chunk] for i in range(s)]

    half = s // 2
    combos = list(itertools.combinations(range(s), half))
    if len(combos) > max_combos:
        # Systematic subsample for tractability
        step = max(1, len(combos) // max_combos)
        combos = combos[::step][:max_combos]

    overfit = 0
    evaluated = 0
    for is_idx in combos:
        oos_idx = [i for i in range(s) if i not in is_idx]
        is_rows: list[list[float]] = []
        oos_rows: list[list[float]] = []
        for gi in is_idx:
            is_rows.extend(groups[gi])
        for gi in oos_idx:
            oos_rows.extend(groups[gi])
        if len(is_rows) < 5 or len(oos_rows) < 5:
            continue
        is_sharpes = [_sharpe_col([row[j] for row in is_rows], periods_per_year) for j in range(k)]
        oos_sharpes = [_sharpe_col([row[j] for row in oos_rows], periods_per_year) for j in range(k)]
        best = max(range(k), key=lambda j: is_sharpes[j])
        # Relative rank of best-IS on OOS (0=worst … 1=best)
        better = sum(1 for j in range(k) if oos_sharpes[j] < oos_sharpes[best])
        rank_rel = (better + 1) / k  # higher = better OOS
        # Overfit token ω = 1 when OOS performance of IS-best is below median
        if rank_rel < 0.5:
            overfit += 1
        evaluated += 1

    if evaluated == 0:
        return {"ok": False, "pbo": None, "error": "no_combos_evaluated"}
    pbo = overfit / evaluated
    return {
        "ok": True,
        "pbo": round(pbo, 6),
        "n_trials": k,
        "n_obs": usable,
        "n_groups": s,
        "combos_evaluated": evaluated,
        "overfit_tokens": overfit,
        "note": "High PBO → IS ranking poorly predicts OOS; report, do not hard-gate alone.",
    }


def trial_matrix_from_param_curves(
    curves: dict[str, Sequence[dict]],
) -> tuple[list[list[float]], list[str]]:
    """Align equity curves by date into T×K simple returns."""
    from lab.validation.returns import equity_curve_to_returns

    # Prefer date alignment
    by_name: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    for name, curve in curves.items():
        m: dict[str, float] = {}
        prev = None
        for row in curve:
            if not isinstance(row, dict):
                continue
            d = str(row.get("date") or "")[:10]
            try:
                eq = float(row.get("equity"))
            except (TypeError, ValueError):
                continue
            if prev is not None and prev != 0 and d:
                m[d] = eq / prev - 1.0
                all_dates.add(d)
            prev = eq
        by_name[name] = m
    dates = sorted(all_dates)
    names = sorted(by_name)
    mat = []
    for d in dates:
        if all(d in by_name[n] for n in names):
            mat.append([by_name[n][d] for n in names])
    if not mat:
        # Fallback: truncate to min length without dates
        rets = {n: equity_curve_to_returns(curves[n]) for n in names}
        mlen = min((len(v) for v in rets.values()), default=0)
        mat = [[rets[n][i] for n in names] for i in range(mlen)]
    return mat, names
