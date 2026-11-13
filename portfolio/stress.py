# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Sequence

from portfolio.risk_contribution import historical_var_cvar


def shock_portfolio_return(
    weights: Sequence[float],
    asset_shocks: Sequence[float],
) -> float:
    return sum(float(w) * float(s) for w, s in zip(weights, asset_shocks))


def stress_table(
    weights: Sequence[float],
    names: Sequence[str],
    *,
    shocks: dict[str, Sequence[float]] | None = None,
) -> list[dict]:
    """Named scenario shocks applied to equal-length weight vector."""
    shocks = shocks or {
        "uniform_-2pct": [-0.02] * len(weights),
        "uniform_-5pct": [-0.05] * len(weights),
        "first_leg_-8pct": [-0.08 if i == 0 else -0.01 for i in range(len(weights))],
    }
    rows = []
    for name, sh in shocks.items():
        if len(sh) != len(weights):
            continue
        rows.append(
            {
                "scenario": name,
                "port_ret": round(shock_portfolio_return(weights, sh), 6),
                "names": list(names),
            }
        )
    return rows


def series_risk_summary(port_returns: Sequence[float]) -> dict:
    from lab.validation.returns import moments

    m = moments(port_returns)
    vc = historical_var_cvar(port_returns, alpha=0.05)
    return {
        "n": m["n"],
        "sharpe": None if m["sharpe"] is None else round(float(m["sharpe"]), 4),
        "var_5": vc["var"],
        "cvar_5": vc["cvar"],
    }
