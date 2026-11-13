# -*- coding: utf-8 -*-
"""Marginal risk contribution + simple CVaR (research / shadow)."""
from __future__ import annotations

import math
from typing import Sequence


def portfolio_vol(weights: Sequence[float], cov: Sequence[Sequence[float]]) -> float:
    n = len(weights)
    var = 0.0
    for i in range(n):
        for j in range(n):
            var += float(weights[i]) * float(weights[j]) * float(cov[i][j])
    return math.sqrt(max(var, 0.0))


def marginal_risk_contribution(
    weights: Sequence[float],
    cov: Sequence[Sequence[float]],
) -> list[float]:
    """MRC_i = w_i * (Σ w)_i / σ_p."""
    n = len(weights)
    sig = portfolio_vol(weights, cov)
    if sig <= 0:
        return [0.0] * n
    out = []
    for i in range(n):
        m = sum(float(cov[i][j]) * float(weights[j]) for j in range(n))
        out.append(float(weights[i]) * m / sig)
    return out


def cov_from_returns(returns_tk: Sequence[Sequence[float]]) -> list[list[float]]:
    """Sample covariance of columns (T×K)."""
    if not returns_tk:
        return []
    t = len(returns_tk)
    k = len(returns_tk[0])
    cols = [[float(returns_tk[i][j]) for i in range(t)] for j in range(k)]
    means = [sum(c) / len(c) for c in cols]
    cov = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            s = sum((cols[i][u] - means[i]) * (cols[j][u] - means[j]) for u in range(t)) / max(t - 1, 1)
            cov[i][j] = cov[j][i] = s
    return cov


def historical_var_cvar(
    returns: Sequence[float],
    *,
    alpha: float = 0.05,
) -> dict[str, float | None]:
    xs = sorted(float(x) for x in returns)
    if not xs:
        return {"var": None, "cvar": None, "alpha": alpha, "n": 0}
    # losses as negative returns: VaR at alpha left tail
    idx = max(0, int(math.floor(alpha * len(xs))) - 1)
    var = xs[idx]
    tail = xs[: idx + 1] or [var]
    cvar = sum(tail) / len(tail)
    return {"var": round(var, 6), "cvar": round(cvar, 6), "alpha": alpha, "n": len(xs)}
