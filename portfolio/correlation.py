# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from typing import Sequence


def corr_matrix(returns_tk: Sequence[Sequence[float]]) -> list[list[float]]:
    """Pearson correlation across columns of a T×K return matrix."""
    if not returns_tk:
        return []
    t = len(returns_tk)
    k = len(returns_tk[0])
    cols = [[float(returns_tk[i][j]) for i in range(t)] for j in range(k)]
    means = [sum(c) / len(c) for c in cols]
    stds = []
    for c, m in zip(cols, means):
        v = sum((x - m) ** 2 for x in c) / max(len(c) - 1, 1)
        stds.append(math.sqrt(v) if v > 0 else 0.0)
    out = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
    for i in range(k):
        for j in range(i + 1, k):
            if stds[i] <= 0 or stds[j] <= 0:
                r = 0.0
            else:
                cov = sum((cols[i][u] - means[i]) * (cols[j][u] - means[j]) for u in range(t)) / max(
                    t - 1, 1
                )
                r = cov / (stds[i] * stds[j])
            out[i][j] = out[j][i] = float(r)
    return out


def max_pairwise_corr(mat: Sequence[Sequence[float]]) -> float | None:
    best = None
    k = len(mat)
    for i in range(k):
        for j in range(i + 1, k):
            v = abs(float(mat[i][j]))
            best = v if best is None else max(best, v)
    return best
