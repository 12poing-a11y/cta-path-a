# -*- coding: utf-8 -*-
"""Shadow portfolio correlation / MRC / CVaR from strategy equity curves."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from portfolio import align_strategy_returns, corr_matrix, max_pairwise_corr  # noqa: E402
from portfolio.risk_contribution import (  # noqa: E402
    cov_from_returns,
    historical_var_cvar,
    marginal_risk_contribution,
    portfolio_vol,
)
from portfolio.stress import series_risk_summary, stress_table  # noqa: E402
from research.governance import register_experiment  # noqa: E402


def _load_curve(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("equity_curve") or []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--curves",
        default="path_a=historical_backtest_latest.json",
        help="name=path pairs comma-separated",
    )
    args = ap.parse_args(argv)
    curves = {}
    for part in args.curves.split(","):
        if "=" not in part:
            continue
        name, rel = part.split("=", 1)
        curves[name.strip()] = _load_curve(ROOT / rel.strip())
    curves = {k: v for k, v in curves.items() if len(v) >= 5}
    if len(curves) < 1:
        # single path-a still useful for CVaR
        c = _load_curve(ROOT / "historical_backtest_latest.json")
        if not c:
            print("[port] no curves")
            return 1
        curves = {"path_a": c}

    names, dates, mat = align_strategy_returns(curves)
    if len(names) >= 2 and mat:
        corr = corr_matrix(mat)
        cov = cov_from_returns(mat)
        w = [1.0 / len(names)] * len(names)
        mrc = marginal_risk_contribution(w, cov)
        port = [sum(w[j] * mat[i][j] for j in range(len(names))) for i in range(len(mat))]
    else:
        # single series
        names = list(curves)
        from lab.validation.returns import equity_curve_to_returns

        rets = equity_curve_to_returns(curves[names[0]])
        mat = [[r] for r in rets]
        corr = [[1.0]]
        cov = cov_from_returns(mat)
        w = [1.0]
        mrc = [1.0]
        port = rets
        dates = []

    summary = series_risk_summary(port)
    vc = historical_var_cvar(port, alpha=0.05)
    payload = {
        "ok": True,
        "schema": "cta-portfolio-risk-v1",
        "names": names,
        "n_obs": len(mat),
        "corr": corr,
        "max_pairwise_corr": max_pairwise_corr(corr),
        "weights": w,
        "mrc": [round(x, 6) for x in mrc],
        "port_vol": round(portfolio_vol(w, cov), 6) if cov else None,
        "var_cvar": vc,
        "summary": summary,
        "stress": stress_table(w, names),
        "live_trading": False,
        "status": "Research",
        "note": "Equal-weight shadow analysis; does not resize formal book.",
    }
    out = ROOT / "lab" / "research" / "portfolio" / "portfolio_risk_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[port] names={names} n={payload['n_obs']} max_corr={payload['max_pairwise_corr']} "
        f"cvar5={vc.get('cvar')} → {out.relative_to(ROOT)}"
    )
    register_experiment(
        name="portfolio_risk_shadow",
        kind="portfolio_risk",
        params={"names": names},
        metrics={"max_corr": payload["max_pairwise_corr"], "cvar_5": vc.get("cvar")},
        artifact=str(out.relative_to(ROOT)),
        status="Research",
        root=ROOT,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
