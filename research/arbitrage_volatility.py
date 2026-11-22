# -*- coding: utf-8 -*-
"""Pair-spread volatility risk engine (research/shadow only).

No network, broker, or paper_book writes. Hedge ratios are estimated using
strictly prior observations; current-bar prices never enter their own fit.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Sequence


def _finite_number(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _finite_positive(value: Any) -> float | None:
    x = _finite_number(value)
    return x if x is not None and x > 0 else None


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _sample_std(xs: Sequence[float]) -> float | None:
    if len(xs) < 2:
        return None
    mu = _mean(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(max(var, 0.0))


def _ols(x: Sequence[float], y: Sequence[float]) -> tuple[float, float] | None:
    """Return intercept, slope for y = intercept + slope*x."""
    if len(x) != len(y) or len(x) < 3:
        return None
    mx, my = _mean(x), _mean(y)
    denom = sum((v - mx) ** 2 for v in x)
    if denom <= 1e-14:
        return None
    beta = sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / denom
    alpha = my - beta * mx
    if not math.isfinite(alpha) or not math.isfinite(beta):
        return None
    return alpha, beta


def rolling_spread(
    rows: Sequence[dict],
    *,
    lookback: int = 60,
    min_observations: int = 30,
    date_key: str = "date",
    leg_a_key: str = "leg_a_close",
    leg_b_key: str = "leg_b_close",
) -> list[dict]:
    """Build A - beta*B - intercept using OLS fit on prior rows only.

    Input rows must already be date-aligned. Missing or invalid bars are kept
    as invalid observations; they are never forward-filled or silently joined.
    """
    if lookback < 3 or min_observations < 3 or min_observations > lookback:
        raise ValueError("invalid lookback/min_observations")
    out: list[dict] = []
    clean_a: list[float] = []
    clean_b: list[float] = []
    previous_date = ""
    for row in rows or []:
        day = str(row.get(date_key) or "")[:10]
        a = _finite_positive(row.get(leg_a_key))
        b = _finite_positive(row.get(leg_b_key))
        try:
            date.fromisoformat(day)
            valid_date = len(day) == 10 and day > previous_date
        except ValueError:
            valid_date = False
        if valid_date:
            previous_date = day
        if not valid_date or a is None or b is None:
            out.append({
                "date": day, "ok": False, "reason": "invalid_or_unsorted_bar",
                "leg_a": a, "leg_b": b, "intercept": None, "hedge_ratio": None,
                "spread": None,
            })
            continue
        # Fit on prior aligned valid rows only. No current-row leakage.
        prior_a = clean_a[-lookback:]
        prior_b = clean_b[-lookback:]
        fit = _ols(prior_b, prior_a) if len(prior_a) >= min_observations else None
        if fit is None:
            out.append({
                "date": day, "ok": False, "reason": "insufficient_fit_history",
                "leg_a": a, "leg_b": b, "intercept": None, "hedge_ratio": None,
                "spread": None,
            })
        else:
            intercept, beta = fit
            spread = a - beta * b - intercept
            out.append({
                "date": day, "ok": math.isfinite(spread),
                "reason": "" if math.isfinite(spread) else "non_finite_spread",
                "leg_a": a, "leg_b": b, "intercept": intercept,
                "hedge_ratio": beta, "spread": spread if math.isfinite(spread) else None,
                "fit_n": len(prior_a),
            })
        clean_a.append(a)
        clean_b.append(b)
    return out


def _rolling_std(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return _sample_std(values[-window:])


def spread_volatility(
    spread_rows: Sequence[dict],
    *,
    short_window: int = 5,
    long_window: int = 60,
    ewma_lambda: float = 0.94,
) -> dict[str, Any]:
    """Measure spread-change volatility, not either leg's standalone ATR."""
    if short_window < 2 or long_window < short_window:
        raise ValueError("invalid volatility windows")
    if not 0.0 < ewma_lambda < 1.0:
        raise ValueError("ewma_lambda must be between 0 and 1")
    valid = [r for r in (spread_rows or []) if r.get("ok") and r.get("spread") is not None]
    spreads = [float(r["spread"]) for r in valid]
    changes = [spreads[i] - spreads[i - 1] for i in range(1, len(spreads))]
    short = _rolling_std(changes, short_window)
    long = _rolling_std(changes, long_window)
    ewma_var = None
    if changes:
        ewma_var = changes[0] ** 2
        for change in changes[1:]:
            ewma_var = ewma_lambda * ewma_var + (1.0 - ewma_lambda) * change ** 2
    ewma = math.sqrt(max(ewma_var, 0.0)) if ewma_var is not None else None
    ratio = short / long if short is not None and long is not None and long > 1e-12 else None
    latest = spreads[-1] if spreads else None
    z = None
    if len(spreads) >= long_window:
        sample = spreads[-long_window:]
        sd = _sample_std(sample)
        if sd is not None and sd > 1e-12:
            z = (latest - _mean(sample)) / sd
    return {
        "ok": latest is not None and long is not None and ewma is not None,
        "asof": valid[-1].get("date") if valid else None,
        "n_spreads": len(spreads),
        "n_changes": len(changes),
        "spread": latest,
        "spread_z": z,
        "vol_short": short,
        "vol_long": long,
        "vol_ewma": ewma,
        "vol_expansion_ratio": ratio,
        "regime": (
            "expand" if ratio is not None and ratio >= 1.6
            else "compress" if ratio is not None and ratio <= 0.7
            else "normal" if ratio is not None else "unknown"
        ),
    }


def pair_correlation(
    leg_a_closes: Sequence[float],
    leg_b_closes: Sequence[float],
    *,
    window: int = 60,
) -> float | None:
    """Pearson correlation of synchronized simple returns."""
    if len(leg_a_closes) != len(leg_b_closes) or len(leg_a_closes) < window + 1:
        return None
    a = [_finite_positive(x) for x in leg_a_closes[-window - 1:]]
    b = [_finite_positive(x) for x in leg_b_closes[-window - 1:]]
    if any(x is None for x in a + b):
        return None
    ra = [a[i] / a[i - 1] - 1.0 for i in range(1, len(a))]
    rb = [b[i] / b[i - 1] - 1.0 for i in range(1, len(b))]
    ma, mb = _mean(ra), _mean(rb)
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((x - mb) ** 2 for x in rb)
    if va <= 1e-16 or vb <= 1e-16:
        return None
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(len(ra)))
    return max(-1.0, min(1.0, cov / math.sqrt(va * vb)))


def evaluate_risk_gate(
    *,
    volatility: dict,
    correlation: float | None,
    hedge_ratio: float | None,
    min_correlation: float = 0.30,
    max_expansion_ratio: float = 2.50,
    max_abs_hedge_ratio: float = 20.0,
) -> dict[str, Any]:
    """Fail-closed risk gate. A missing critical input blocks new risk."""
    reasons: list[str] = []
    if not volatility or not volatility.get("ok"):
        reasons.append("spread_volatility_unavailable")
    corr = _finite_number(correlation)
    if corr is None:
        reasons.append("correlation_unavailable")
    elif abs(corr) < min_correlation:
        reasons.append("correlation_breakdown")
    beta = _finite_number(hedge_ratio)
    if beta is None:
        reasons.append("hedge_ratio_unavailable")
    elif abs(beta) > max_abs_hedge_ratio or abs(beta) < 1e-8:
        reasons.append("hedge_ratio_out_of_bounds")
    ratio = _finite_number((volatility or {}).get("vol_expansion_ratio"))
    if ratio is None:
        reasons.append("volatility_ratio_unavailable")
    elif ratio > max_expansion_ratio:
        reasons.append("extreme_spread_volatility")
    return {
        "allow_new_risk": not reasons,
        "status": "PASS" if not reasons else "BLOCK",
        "reasons": reasons,
        "correlation": corr,
        "hedge_ratio": beta,
        "vol_expansion_ratio": ratio,
        "mode": "shadow_only",
    }


def size_pair_position(
    *,
    risk_budget_yuan: float,
    spread_vol_points: float | None,
    multiplier_a: float,
    multiplier_b: float,
    hedge_ratio: float | None,
    max_a_contracts: int = 10,
    gate: dict | None = None,
) -> dict[str, Any]:
    """Risk-budget sizing for 1 A contract and rounded B hedge contracts.

    One spread sigma is approximated by vol_points * multiplier_a. The B-leg
    contract count is beta * multiplier_a / multiplier_b. This is a sizing
    approximation; exchange margin, tick rounding, fees and slippage are
    separate constraints and must be added by the execution simulator.
    """
    vals = (risk_budget_yuan, multiplier_a, multiplier_b)
    if any(not math.isfinite(float(v)) or float(v) <= 0 for v in vals):
        raise ValueError("risk budget and multipliers must be positive finite values")
    if int(max_a_contracts) < 1:
        raise ValueError("max_a_contracts must be at least 1")
    blocked = not gate or not bool(gate.get("allow_new_risk"))
    if blocked:
        return {
            "ok": False, "status": "BLOCK", "contracts_a": 0, "contracts_b": 0,
            "risk_per_pair_yuan": None, "risk_budget_yuan": float(risk_budget_yuan),
            "reason": "risk_gate_blocked",
        }
    if spread_vol_points is None or not math.isfinite(float(spread_vol_points)) or spread_vol_points <= 0:
        return {
            "ok": False, "status": "BLOCK", "contracts_a": 0, "contracts_b": 0,
            "risk_per_pair_yuan": None, "risk_budget_yuan": float(risk_budget_yuan),
            "reason": "spread_volatility_unavailable",
        }
    beta = float(hedge_ratio) if hedge_ratio is not None else math.nan
    if not math.isfinite(beta) or abs(beta) < 1e-8:
        return {
            "ok": False, "status": "BLOCK", "contracts_a": 0, "contracts_b": 0,
            "risk_per_pair_yuan": None, "risk_budget_yuan": float(risk_budget_yuan),
            "reason": "invalid_hedge_ratio",
        }
    risk_per_pair = float(spread_vol_points) * float(multiplier_a)
    raw = int(math.floor(float(risk_budget_yuan) / risk_per_pair))
    contracts_a = max(0, min(int(max_a_contracts), raw))
    contracts_b = int(round(abs(beta) * float(multiplier_a) / float(multiplier_b) * contracts_a))
    # Never return a one-legged recommendation when integer rounding removes the hedge.
    if contracts_b <= 0:
        contracts_a = 0
        contracts_b = 0
    return {
        "ok": contracts_a > 0 and contracts_b > 0,
        "status": "SIZED" if contracts_a > 0 and contracts_b > 0 else "BLOCK",
        "contracts_a": contracts_a,
        "contracts_b": contracts_b,
        "leg_b_direction": "short" if beta > 0 else "long",
        "risk_per_pair_yuan": round(risk_per_pair, 2),
        "estimated_risk_yuan": round(contracts_a * risk_per_pair, 2),
        "risk_budget_yuan": float(risk_budget_yuan),
        "hedge_ratio": beta,
        "mode": "shadow_only",
        "note": "未计保证金、跳空、手续费、滑点及最小手数约束；不可直接用于实盘下单。",
    }
