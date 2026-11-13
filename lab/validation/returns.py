# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from typing import Any, Sequence


def day_pnls_to_returns(day_pnls: Sequence[dict[str, Any]], *, equity0: float | None = None) -> list[float]:
    """Prefer pnl/equity_prev; fall back to equity path diffs."""
    rows = [r for r in day_pnls if isinstance(r, dict)]
    if not rows:
        return []
    out: list[float] = []
    prev_eq = float(equity0) if equity0 not in (None, 0) else None
    for r in rows:
        pnl = r.get("pnl")
        eq = r.get("equity")
        try:
            pnl_f = float(pnl) if pnl is not None else None
            eq_f = float(eq) if eq is not None else None
        except (TypeError, ValueError):
            continue
        if prev_eq is None and eq_f is not None and pnl_f is not None:
            prev_eq = eq_f - pnl_f
        if prev_eq is not None and prev_eq != 0 and pnl_f is not None:
            out.append(pnl_f / prev_eq)
            if eq_f is not None:
                prev_eq = eq_f
            else:
                prev_eq = prev_eq + pnl_f
        elif eq_f is not None and prev_eq is not None and prev_eq != 0:
            out.append(eq_f / prev_eq - 1.0)
            prev_eq = eq_f
        elif eq_f is not None:
            prev_eq = eq_f
    return out


def equity_curve_to_returns(curve: Sequence[dict[str, Any]]) -> list[float]:
    eqs: list[float] = []
    for r in curve:
        if not isinstance(r, dict):
            continue
        try:
            eqs.append(float(r.get("equity")))
        except (TypeError, ValueError):
            continue
    out: list[float] = []
    for i in range(1, len(eqs)):
        if eqs[i - 1] == 0:
            continue
        out.append(eqs[i] / eqs[i - 1] - 1.0)
    return out


def moments(returns: Sequence[float]) -> dict[str, float | int | None]:
    xs = [float(x) for x in returns if x is not None and math.isfinite(float(x))]
    n = len(xs)
    if n < 2:
        return {"n": n, "mean": None, "std": None, "skew": None, "kurtosis": None, "sharpe": None}
    mu = sum(xs) / n
    var = sum((x - mu) ** 2 for x in xs) / max(n - 1, 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd <= 0:
        skew = 0.0
        kurt = 0.0
        sharpe = None
    else:
        m3 = sum((x - mu) ** 3 for x in xs) / n
        m4 = sum((x - mu) ** 4 for x in xs) / n
        skew = m3 / (sd**3)
        # Fisher excess kurtosis (normal → 0); PSR uses non-excess γ4 = kurtosis+3 in some texts.
        # We store excess; callers convert.
        kurt = m4 / (sd**4) - 3.0
        sharpe = (mu / sd) * math.sqrt(252.0)
    return {
        "n": n,
        "mean": mu,
        "std": sd,
        "skew": skew,
        "kurtosis": kurt,  # excess
        "sharpe": None if sharpe is None else float(sharpe),
    }
