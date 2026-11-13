# -*- coding: utf-8 -*-
"""Estimate effective independent trials from a trial correlation structure."""
from __future__ import annotations

import math
from typing import Sequence


def effective_trials(
    n_trials: int,
    *,
    mean_abs_corr: float | None = None,
    corr_matrix: Sequence[Sequence[float]] | None = None,
) -> dict:
    """Bailey–LdP style effective number of trials.

    If corr_matrix given (KxK), use average pairwise |ρ|.
    Else use mean_abs_corr (default 0 → N_eff = N).
    N_eff = N * (1 − ρ̄) + ρ̄  (clamped to [1, N]).
    """
    n = max(0, int(n_trials))
    if n <= 0:
        return {"ok": False, "n_trials": n, "n_eff": None, "mean_abs_corr": None}
    if n == 1:
        return {"ok": True, "n_trials": 1, "n_eff": 1.0, "mean_abs_corr": 0.0}

    rho = mean_abs_corr
    if corr_matrix is not None:
        k = len(corr_matrix)
        acc = 0.0
        cnt = 0
        for i in range(k):
            row = corr_matrix[i]
            for j in range(i + 1, k):
                try:
                    acc += abs(float(row[j]))
                    cnt += 1
                except (TypeError, ValueError, IndexError):
                    continue
        rho = (acc / cnt) if cnt else 0.0

    if rho is None:
        rho = 0.0
    rho = max(0.0, min(1.0, float(rho)))
    n_eff = n * (1.0 - rho) + rho
    n_eff = max(1.0, min(float(n), n_eff))
    return {
        "ok": True,
        "n_trials": n,
        "n_eff": round(n_eff, 4),
        "mean_abs_corr": round(rho, 6),
        "note": "Higher correlation among trials → fewer effective independent tries.",
    }


def pairwise_corr(returns_matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    """Pearson corr across columns (each column = one trial's return series)."""
    if not returns_matrix:
        return []
    # returns_matrix as T x K
    t = len(returns_matrix)
    k = len(returns_matrix[0]) if t else 0
    cols = [[float(returns_matrix[i][j]) for i in range(t)] for j in range(k)]
    means = [sum(c) / len(c) for c in cols]
    stds = []
    for c, m in zip(cols, means):
        v = sum((x - m) ** 2 for x in c) / max(len(c) - 1, 1)
        stds.append(math.sqrt(v) if v > 0 else 0.0)
    mat = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
    for i in range(k):
        for j in range(i + 1, k):
            if stds[i] <= 0 or stds[j] <= 0:
                r = 0.0
            else:
                cov = sum((cols[i][t_] - means[i]) * (cols[j][t_] - means[j]) for t_ in range(t)) / max(
                    t - 1, 1
                )
                r = cov / (stds[i] * stds[j])
            mat[i][j] = mat[j][i] = float(r)
    return mat
