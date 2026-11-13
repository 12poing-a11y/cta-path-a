# -*- coding: utf-8 -*-
from portfolio.risk_contribution import (
    cov_from_returns,
    historical_var_cvar,
    marginal_risk_contribution,
    portfolio_vol,
)
from portfolio.stress import shock_portfolio_return


def test_mrc_sums_to_vol():
    mat = [[0.01, 0.005], [0.0, -0.002], [0.012, 0.008], [-0.01, -0.004], [0.003, 0.001]]
    cov = cov_from_returns(mat)
    w = [0.6, 0.4]
    sig = portfolio_vol(w, cov)
    mrc = marginal_risk_contribution(w, cov)
    assert abs(sum(mrc) - sig) < 1e-9


def test_cvar_left_tail():
    rets = [-0.05, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03]
    out = historical_var_cvar(rets, alpha=0.3)
    assert out["var"] is not None and out["cvar"] is not None
    assert out["cvar"] <= out["var"] + 1e-9


def test_shock():
    assert abs(shock_portfolio_return([0.5, 0.5], [-0.02, -0.02]) - (-0.02)) < 1e-12
