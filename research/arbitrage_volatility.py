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
    cointegration: dict | None = None,
    require_cointegration: bool = False,
    max_half_life: float | None = 60.0,
) -> dict[str, Any]:
    """Fail-closed risk gate. A missing critical input blocks new risk.

    When ``require_cointegration`` is True, a missing/failed Engle-Granger
    diagnostic or an excessive residual half-life also blocks new risk.
    """
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
    coint_ok = None
    half_life = None
    if require_cointegration:
        if not cointegration or not isinstance(cointegration, dict):
            reasons.append("cointegration_unavailable")
        else:
            coint_ok = bool(cointegration.get("ok"))
            half_life = _finite_number(cointegration.get("half_life"))
            if not coint_ok:
                reasons.append("cointegration_failed")
            if half_life is None:
                reasons.append("half_life_unavailable")
            elif max_half_life is not None and half_life > float(max_half_life):
                reasons.append("half_life_too_long")
            if cointegration.get("break_flag"):
                reasons.append("residual_structure_break")
    return {
        "allow_new_risk": not reasons,
        "status": "PASS" if not reasons else "BLOCK",
        "reasons": reasons,
        "correlation": corr,
        "hedge_ratio": beta,
        "vol_expansion_ratio": ratio,
        "cointegration_ok": coint_ok,
        "half_life": half_life,
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


# ---------------------------------------------------------------------------
# V1.1 — alignment, contract specs, Engle-Granger / ADF / half-life
# ---------------------------------------------------------------------------

# Approximate MacKinnon (1991) critical values for ADF residual test, no constant
# in the residual regression beyond the EG residual mean (tau_c style approx).
_ADF_CRIT_5 = -2.86
_ADF_CRIT_1 = -3.43


def align_pair_bars(
    leg_a: Sequence[dict],
    leg_b: Sequence[dict],
    *,
    date_key: str = "date",
    price_key: str = "close",
    volume_key: str = "volume",
    oi_key: str = "open_interest",
) -> dict[str, Any]:
    """Inner-join two leg bar series on calendar date. Never forward-fills.

    Bars missing on either leg are dropped (not carried). Output rows keep
    optional volume/OI when both sides provide finite values.
    """
    def _index(rows: Sequence[dict]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        prev = ""
        for row in rows or []:
            day = str(row.get(date_key) or "")[:10]
            try:
                date.fromisoformat(day)
                ok_day = len(day) == 10 and day > prev
            except ValueError:
                ok_day = False
            if not ok_day:
                continue
            prev = day
            px = _finite_positive(row.get(price_key))
            if px is None:
                continue
            out[day] = row
        return out

    ia, ib = _index(leg_a), _index(leg_b)
    common = sorted(set(ia) & set(ib))
    aligned: list[dict] = []
    for day in common:
        ra, rb = ia[day], ib[day]
        a = _finite_positive(ra.get(price_key))
        b = _finite_positive(rb.get(price_key))
        if a is None or b is None:
            continue
        row = {
            "date": day,
            "leg_a_close": a,
            "leg_b_close": b,
            "leg_a_volume": _finite_number(ra.get(volume_key)),
            "leg_b_volume": _finite_number(rb.get(volume_key)),
            "leg_a_oi": _finite_number(ra.get(oi_key)),
            "leg_b_oi": _finite_number(rb.get(oi_key)),
        }
        # Prefer next-day open fields when present (V1.2 fill); else absent.
        for src, dst in (
            (ra.get("open"), "leg_a_open"),
            (rb.get("open"), "leg_b_open"),
            (ra.get("high"), "leg_a_high"),
            (rb.get("high"), "leg_b_high"),
            (ra.get("low"), "leg_a_low"),
            (rb.get("low"), "leg_b_low"),
        ):
            v = _finite_positive(src)
            if v is not None:
                row[dst] = v
        aligned.append(row)
    dropped_a = len(ia) - len(common)
    dropped_b = len(ib) - len(common)
    return {
        "ok": len(aligned) >= 3,
        "rows": aligned,
        "n": len(aligned),
        "dropped_a_only": dropped_a,
        "dropped_b_only": dropped_b,
        "fill_policy": "inner_join_no_ffill",
    }


def contract_spec_from_universe_row(row: dict | None) -> dict[str, Any] | None:
    """Normalize Path-A universe symbol fields into a research contract spec."""
    if not isinstance(row, dict) or not row.get("code"):
        return None
    mult = _finite_positive(row.get("mult") or row.get("multiplier"))
    tick = _finite_positive(row.get("tick"))
    if mult is None or tick is None:
        return None
    fee_yuan = _finite_number(row.get("fee_yuan")) or 0.0
    fee_rate = _finite_number(row.get("fee_rate")) or 0.0
    margin_rate = _finite_positive(row.get("margin_rate")) or 0.12
    limit_pct = _finite_positive(row.get("limit_pct")) or 0.07
    return {
        "code": str(row["code"]).upper(),
        "name": str(row.get("name") or ""),
        "bucket": str(row.get("bucket") or ""),
        "mult": float(mult),
        "tick": float(tick),
        "fee_yuan": float(fee_yuan),
        "fee_rate": float(fee_rate),
        "margin_rate": float(margin_rate),
        "limit_pct": float(limit_pct),
    }


def adf_tstat(series: Sequence[float], *, lags: int = 0) -> dict[str, Any]:
    """Stdlib ADF(0) style t-stat: Δy = α + β y_{t-1} (+ lag Δy if lags>0)."""
    y = [float(v) for v in series if _finite_number(v) is not None]
    if len(y) < 20:
        return {"ok": False, "reason": "insufficient_sample", "tstat": None, "n": len(y)}
    dy = [y[i] - y[i - 1] for i in range(1, len(y))]
    level = y[:-1]
    # Build regression dy_t = a + b*y_{t-1} + sum c_k dy_{t-k}
    n = len(dy)
    if lags < 0 or lags >= n - 3:
        return {"ok": False, "reason": "invalid_lags", "tstat": None, "n": n}
    rows_x: list[list[float]] = []
    rows_y: list[float] = []
    for t in range(lags, n):
        x = [1.0, level[t]]
        for k in range(1, lags + 1):
            x.append(dy[t - k])
        rows_x.append(x)
        rows_y.append(dy[t])
    k = len(rows_x[0])
    # OLS via normal equations (small k).
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for i in range(len(rows_x)):
        for r in range(k):
            xty[r] += rows_x[i][r] * rows_y[i]
            for c in range(k):
                xtx[r][c] += rows_x[i][r] * rows_x[i][c]
    beta = _solve_linear(xtx, xty)
    if beta is None:
        return {"ok": False, "reason": "singular", "tstat": None, "n": len(rows_y)}
    resid = [
        rows_y[i] - sum(beta[j] * rows_x[i][j] for j in range(k))
        for i in range(len(rows_y))
    ]
    dof = len(resid) - k
    if dof < 1:
        return {"ok": False, "reason": "dof", "tstat": None, "n": len(resid)}
    sse = sum(r * r for r in resid)
    sigma2 = sse / dof
    # Var(beta) ≈ sigma2 * (X'X)^{-1}
    inv = _invert_matrix(xtx)
    if inv is None or inv[1][1] <= 0 or sigma2 <= 0:
        return {"ok": False, "reason": "se_unavailable", "tstat": None, "n": len(resid)}
    se_b = math.sqrt(sigma2 * inv[1][1])
    if se_b <= 1e-14:
        return {"ok": False, "reason": "se_zero", "tstat": None, "n": len(resid)}
    tstat = beta[1] / se_b
    return {
        "ok": True,
        "tstat": tstat,
        "beta": beta[1],
        "n": len(resid),
        "reject_5pct": tstat < _ADF_CRIT_5,
        "reject_1pct": tstat < _ADF_CRIT_1,
        "crit_5pct": _ADF_CRIT_5,
        "crit_1pct": _ADF_CRIT_1,
    }


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-14:
            return None
        m[col], m[piv] = m[piv], m[col]
        div = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            fac = m[r][col]
            for j in range(col, n + 1):
                m[r][j] -= fac * m[col][j]
    return [m[i][n] for i in range(n)]


def _invert_matrix(a: list[list[float]]) -> list[list[float]] | None:
    n = len(a)
    m = [a[i][:] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-14:
            return None
        m[col], m[piv] = m[piv], m[col]
        div = m[col][col]
        for j in range(2 * n):
            m[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            fac = m[r][col]
            for j in range(2 * n):
                m[r][j] -= fac * m[col][j]
    return [row[n:] for row in m]


def half_life_ou(residuals: Sequence[float]) -> dict[str, Any]:
    """AR(1) half-life on residual levels: Δr = λ r_{t-1} + ε."""
    r = [float(v) for v in residuals if _finite_number(v) is not None]
    if len(r) < 20:
        return {"ok": False, "half_life": None, "lambda": None, "reason": "insufficient_sample"}
    x = r[:-1]
    y = [r[i] - r[i - 1] for i in range(1, len(r))]
    mx, my = _mean(x), _mean(y)
    denom = sum((v - mx) ** 2 for v in x)
    if denom <= 1e-14:
        return {"ok": False, "half_life": None, "lambda": None, "reason": "flat_residual"}
    lam = sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / denom
    # Need mean-reverting: -1 < lam < 0  (since Δr = λ r => r_t = (1+λ) r_{t-1})
    phi = 1.0 + lam
    if not (-1.0 < lam < 0.0) or phi <= 0.0 or phi >= 1.0:
        return {
            "ok": False, "half_life": None, "lambda": lam,
            "reason": "not_mean_reverting",
        }
    hl = -math.log(2.0) / math.log(phi)
    if not math.isfinite(hl) or hl <= 0:
        return {"ok": False, "half_life": None, "lambda": lam, "reason": "non_finite_half_life"}
    return {"ok": True, "half_life": hl, "lambda": lam, "reason": ""}


def residual_structure_break(
    residuals: Sequence[float],
    *,
    threshold: float = 0.75,
) -> dict[str, Any]:
    """Flag large shift in residual variance between first/second half."""
    r = [float(v) for v in residuals if _finite_number(v) is not None]
    if len(r) < 40:
        return {"ok": False, "break_flag": False, "reason": "insufficient_sample"}
    mid = len(r) // 2
    s1 = _sample_std(r[:mid])
    s2 = _sample_std(r[mid:])
    if s1 is None or s2 is None or min(s1, s2) <= 1e-12:
        return {"ok": False, "break_flag": False, "reason": "std_unavailable"}
    ratio = max(s1, s2) / min(s1, s2)
    return {
        "ok": True,
        "break_flag": ratio >= (1.0 + float(threshold)),
        "std_first": s1,
        "std_second": s2,
        "std_ratio": ratio,
        "threshold_ratio": 1.0 + float(threshold),
        "reason": "",
    }


def engle_granger(
    leg_a: Sequence[float],
    leg_b: Sequence[float],
    *,
    adf_lags: int = 0,
    max_half_life: float = 60.0,
) -> dict[str, Any]:
    """Engle-Granger: OLS A~B then ADF + half-life on residuals (prior sample)."""
    if len(leg_a) != len(leg_b) or len(leg_a) < 30:
        return {
            "ok": False, "reason": "insufficient_sample",
            "adf": None, "half_life": None, "break_flag": False,
        }
    a = [float(x) for x in leg_a]
    b = [float(x) for x in leg_b]
    if any(not math.isfinite(x) or x <= 0 for x in a + b):
        return {
            "ok": False, "reason": "non_positive_price",
            "adf": None, "half_life": None, "break_flag": False,
        }
    fit = _ols(b, a)
    if fit is None:
        return {
            "ok": False, "reason": "ols_failed",
            "adf": None, "half_life": None, "break_flag": False,
        }
    intercept, beta = fit
    resid = [a[i] - intercept - beta * b[i] for i in range(len(a))]
    adf = adf_tstat(resid, lags=adf_lags)
    hl = half_life_ou(resid)
    br = residual_structure_break(resid)
    coint = bool(adf.get("ok") and adf.get("reject_5pct"))
    hl_ok = bool(hl.get("ok") and hl.get("half_life") is not None
                 and float(hl["half_life"]) <= float(max_half_life))
    ok = coint and hl_ok and not bool(br.get("break_flag"))
    reason = ""
    if not coint:
        reason = "adf_not_rejected"
    elif not hl_ok:
        reason = "half_life_fail"
    elif br.get("break_flag"):
        reason = "structure_break"
    return {
        "ok": ok,
        "reason": reason,
        "intercept": intercept,
        "hedge_ratio": beta,
        "adf": adf,
        "half_life": hl.get("half_life"),
        "half_life_detail": hl,
        "break_flag": bool(br.get("break_flag")),
        "break_detail": br,
        "n": len(resid),
    }


def rolling_cointegration(
    rows: Sequence[dict],
    *,
    lookback: int = 120,
    min_observations: int = 60,
    date_key: str = "date",
    leg_a_key: str = "leg_a_close",
    leg_b_key: str = "leg_b_close",
    max_half_life: float = 60.0,
) -> list[dict]:
    """Point-in-time Engle-Granger using strictly prior aligned rows."""
    if lookback < 30 or min_observations < 30 or min_observations > lookback:
        raise ValueError("invalid lookback/min_observations for cointegration")
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
            out.append({"date": day, "ok": False, "reason": "invalid_or_unsorted_bar"})
            continue
        prior_a = clean_a[-lookback:]
        prior_b = clean_b[-lookback:]
        if len(prior_a) < min_observations:
            out.append({
                "date": day, "ok": False, "reason": "insufficient_fit_history",
                "n": len(prior_a),
            })
        else:
            eg = engle_granger(prior_a, prior_b, max_half_life=max_half_life)
            out.append({"date": day, **eg})
        clean_a.append(a)
        clean_b.append(b)
    return out


def spread_risk_metrics(
    spread_rows: Sequence[dict],
    *,
    short_window: int = 5,
    long_window: int = 60,
    ewma_lambda: float = 0.94,
    es_alpha: float = 0.05,
) -> dict[str, Any]:
    """V1.2 diagnostics: ATR-like, EWMA, percentile, and left-tail ES of Δspread."""
    base = spread_volatility(
        spread_rows,
        short_window=short_window,
        long_window=long_window,
        ewma_lambda=ewma_lambda,
    )
    valid = [r for r in (spread_rows or []) if r.get("ok") and r.get("spread") is not None]
    spreads = [float(r["spread"]) for r in valid]
    changes = [spreads[i] - spreads[i - 1] for i in range(1, len(spreads))]
    pct = None
    es = None
    if len(changes) >= max(20, long_window):
        sample = sorted(changes[-long_window:])
        # historical percentile of |Δspread|
        abs_s = sorted(abs(x) for x in sample)
        pct = abs_s[int(0.95 * (len(abs_s) - 1))]
        # ES of adverse (negative) changes — losses for long-spread book
        left = sorted(sample)
        cut = max(1, int(math.floor(es_alpha * len(left))))
        es = abs(sum(left[:cut]) / cut)
    atr = None
    if len(changes) >= short_window:
        atr = _mean([abs(x) for x in changes[-short_window:]])
    base.update({
        "spread_atr": atr,
        "vol_p95_abs": pct,
        "es_abs": es,
        "es_alpha": es_alpha,
    })
    return base
