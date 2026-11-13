# -*- coding: utf-8 -*-
"""Deflated Sharpe Ratio (Bailey & López de Prado)."""
from __future__ import annotations

import math
from typing import Any, Sequence

from lab.validation.effective_trials import effective_trials
from lab.validation.psr import probabilistic_sharpe_ratio
from lab.validation.returns import moments


def _norm_ppf(p: float) -> float:
    """Approximate inverse CDF of standard normal (Acklam / Beasley-Springer style)."""
    p = min(max(float(p), 1e-12), 1.0 - 1e-12)
    # Coefficients from Peter J. Acklam's approximation
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def expected_max_sharpe(
    n_eff: float,
    *,
    var_sr: float,
    euler_mascheroni: float = 0.5772156649,
) -> float:
    """E[max SR] under null of zero true SR (multiple testing inflation)."""
    n_eff = max(1.0, float(n_eff))
    # SR* ≈ √V[SR] * ((1−γ) Z^{-1}(1−1/N) + γ Z^{-1}(1−1/(N e)))
    z1 = _norm_ppf(1.0 - 1.0 / n_eff)
    z2 = _norm_ppf(1.0 - 1.0 / (n_eff * math.e))
    return math.sqrt(max(var_sr, 0.0)) * ((1.0 - euler_mascheroni) * z1 + euler_mascheroni * z2)


def deflated_sharpe_ratio(
    returns: Sequence[float] | None = None,
    *,
    sharpe: float | None = None,
    n: int | None = None,
    skew: float | None = None,
    kurtosis_excess: float | None = None,
    n_trials: int = 1,
    mean_abs_corr: float | None = 0.0,
    periods_per_year: float = 252.0,
) -> dict[str, Any]:
    """DSR = PSR(SR̂ | SR* = E[max SR under N_eff trials])."""
    if returns is not None:
        m = moments(returns)
        n = int(m["n"] or 0)
        skew = float(m["skew"] or 0.0)
        kurtosis_excess = float(m["kurtosis"] or 0.0)
        sharpe = m["sharpe"]
    if n is None or sharpe is None or n < 2:
        return {"ok": False, "dsr": None, "error": "insufficient_sample"}

    # Non-annualized SR variance under normality ≈ (1 − γ3 SR + (γ4−1)/4 SR²)/(n−1)
    sr_hat = float(sharpe) / math.sqrt(periods_per_year)
    g3 = float(skew or 0.0)
    g4 = float(kurtosis_excess or 0.0) + 3.0
    var_term = 1.0 - g3 * sr_hat + ((g4 - 1.0) / 4.0) * (sr_hat**2)
    var_sr = max(var_term, 1e-12) / max(n - 1, 1)

    et = effective_trials(n_trials, mean_abs_corr=mean_abs_corr)
    n_eff = float(et["n_eff"] or 1.0)
    sr_star_nonann = expected_max_sharpe(n_eff, var_sr=var_sr)
    sr_star_ann = sr_star_nonann * math.sqrt(periods_per_year)

    psr = probabilistic_sharpe_ratio(
        sharpe=float(sharpe),
        n=int(n),
        skew=g3,
        kurtosis_excess=g4 - 3.0,
        sr_benchmark=sr_star_ann,
        periods_per_year=periods_per_year,
    )
    return {
        "ok": bool(psr.get("ok")),
        "dsr": psr.get("psr"),
        "psr_vs_zero": probabilistic_sharpe_ratio(
            sharpe=float(sharpe),
            n=int(n),
            skew=g3,
            kurtosis_excess=g4 - 3.0,
            sr_benchmark=0.0,
            periods_per_year=periods_per_year,
        ).get("psr"),
        "sharpe": round(float(sharpe), 6),
        "sr_benchmark_ann": round(sr_star_ann, 6),
        "n": n,
        "n_trials": int(n_trials),
        "n_eff": et.get("n_eff"),
        "mean_abs_corr": et.get("mean_abs_corr"),
        "note": (
            "DSR corrects for multiple strategy attempts; "
            "do not admit solely because DSR>threshold."
        ),
    }
