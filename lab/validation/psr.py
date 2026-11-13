# -*- coding: utf-8 -*-
"""Probabilistic Sharpe Ratio (Bailey & López de Prado)."""
from __future__ import annotations

import math
from typing import Any, Sequence

from lab.validation.returns import moments


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def probabilistic_sharpe_ratio(
    returns: Sequence[float] | None = None,
    *,
    sharpe: float | None = None,
    n: int | None = None,
    skew: float | None = None,
    kurtosis_excess: float | None = None,
    sr_benchmark: float = 0.0,
    periods_per_year: float = 252.0,
) -> dict[str, Any]:
    """PSR = Φ( (SR̂ − SR*) √(n−1) / √(1 − γ3 SR̂ + (γ4−1)/4 SR̂²) ).

    `kurtosis_excess` is Fisher excess (normal=0); γ4 = excess + 3.
    Sharpe inputs are **annualized**; converted to per-period for the formula.
    """
    if returns is not None:
        m = moments(returns)
        n = int(m["n"] or 0)
        skew = float(m["skew"] or 0.0)
        kurtosis_excess = float(m["kurtosis"] or 0.0)
        sharpe = m["sharpe"]
    if n is None or sharpe is None or n < 2:
        return {"ok": False, "psr": None, "error": "insufficient_sample", "n": n, "sharpe": sharpe}

    sr_hat = float(sharpe) / math.sqrt(float(periods_per_year))
    sr_star = float(sr_benchmark) / math.sqrt(float(periods_per_year))
    g3 = float(skew if skew is not None else 0.0)
    g4 = float(kurtosis_excess if kurtosis_excess is not None else 0.0) + 3.0
    denom_sq = 1.0 - g3 * sr_hat + ((g4 - 1.0) / 4.0) * (sr_hat**2)
    if denom_sq <= 0:
        return {
            "ok": False,
            "psr": None,
            "error": "non_positive_variance_term",
            "n": n,
            "sharpe": float(sharpe),
            "skew": g3,
            "kurtosis_excess": g4 - 3.0,
        }
    z = (sr_hat - sr_star) * math.sqrt(n - 1) / math.sqrt(denom_sq)
    psr = _norm_cdf(z)
    return {
        "ok": True,
        "psr": round(psr, 6),
        "z": round(z, 6),
        "n": n,
        "sharpe": round(float(sharpe), 6),
        "sr_benchmark": float(sr_benchmark),
        "skew": round(g3, 6),
        "kurtosis_excess": round(g4 - 3.0, 6),
        "note": "PSR is not an automatic admission gate; report alongside sample size.",
    }
