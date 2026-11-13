# -*- coding: utf-8 -*-
"""Bundle PSR/DSR/PBO/walk-forward for a return series or backtest day_pnls."""
from __future__ import annotations

from typing import Any, Sequence

from lab.validation.dsr import deflated_sharpe_ratio
from lab.validation.pbo import probability_of_backtest_overfitting
from lab.validation.psr import probabilistic_sharpe_ratio
from lab.validation.returns import day_pnls_to_returns, equity_curve_to_returns, moments
from lab.validation.walk_forward import walk_forward_segments


def validation_bundle_from_returns(
    returns: Sequence[float],
    *,
    n_trials: int = 1,
    mean_abs_corr: float | None = 0.0,
    trial_matrix: Sequence[Sequence[float]] | None = None,
    pbo_groups: int = 8,
    sr_benchmark: float = 0.0,
) -> dict[str, Any]:
    xs = [float(x) for x in returns]
    m = moments(xs)
    psr = probabilistic_sharpe_ratio(xs, sr_benchmark=sr_benchmark)
    dsr = deflated_sharpe_ratio(
        xs, n_trials=n_trials, mean_abs_corr=mean_abs_corr
    )
    wf = walk_forward_segments(xs)
    pbo: dict[str, Any]
    if trial_matrix is not None:
        pbo = probability_of_backtest_overfitting(trial_matrix, n_groups=pbo_groups)
    else:
        pbo = {
            "ok": False,
            "pbo": None,
            "error": "trial_matrix_required",
            "note": "Provide T×K trial returns to estimate PBO; single curve insufficient.",
        }
    return {
        "schema": "cta-validation-bundle-v1",
        "moments": {
            "n": m["n"],
            "sharpe": None if m["sharpe"] is None else round(float(m["sharpe"]), 4),
            "skew": None if m["skew"] is None else round(float(m["skew"]), 4),
            "kurtosis_excess": None
            if m["kurtosis"] is None
            else round(float(m["kurtosis"]), 4),
        },
        "psr": psr,
        "dsr": dsr,
        "pbo": pbo,
        "walk_forward": wf,
        "n_trials_assumed": int(n_trials),
        "live_trading": False,
        "admission": {
            "auto_promote": False,
            "rule": "Report PSR/DSR/PBO; human approval required for Approved tier.",
        },
    }


def validation_bundle_from_day_pnls(
    day_pnls: Sequence[dict[str, Any]],
    *,
    equity0: float | None = None,
    n_trials: int = 1,
    mean_abs_corr: float | None = 0.0,
    trial_matrix: Sequence[Sequence[float]] | None = None,
) -> dict[str, Any]:
    rets = day_pnls_to_returns(day_pnls, equity0=equity0)
    return validation_bundle_from_returns(
        rets,
        n_trials=n_trials,
        mean_abs_corr=mean_abs_corr,
        trial_matrix=trial_matrix,
    )


def _default_n_trials(out: dict[str, Any], root=None) -> int:
    if out.get("n_trials_assumed") is not None:
        return max(1, int(out["n_trials_assumed"]))
    try:
        from pathlib import Path
        import json

        root = Path(root) if root else Path(__file__).resolve().parents[2]
        rules = json.loads((root / "execution_rules.json").read_text(encoding="utf-8"))
        archived = rules.get("archived_params") or []
        # current + archived parameter sets ≈ search intensity lower bound
        return max(1, 1 + len(archived))
    except Exception:
        return 1


def validation_bundle_from_backtest(out: dict[str, Any], *, n_trials: int | None = None) -> dict[str, Any]:
    """Attach-ready bundle from historical_backtest simulate() output."""
    if n_trials is None:
        n_trials = _default_n_trials(out)
    # Prefer full equity curve (day_pnls_tail is only a short window).
    rets = equity_curve_to_returns(out.get("equity_curve") or [])
    if len(rets) < 10:
        day_full = out.get("day_pnls") or out.get("day_pnls_tail") or []
        bundle = validation_bundle_from_day_pnls(
            day_full,
            equity0=out.get("equity_start"),
            n_trials=n_trials,
        )
    else:
        bundle = validation_bundle_from_returns(rets, n_trials=n_trials)
    bundle["source"] = {
        "schema_version": out.get("schema_version"),
        "mode": out.get("mode"),
        "cost_scenario": out.get("cost_scenario"),
        "start": out.get("start"),
        "end": out.get("end"),
    }
    # Merge latest Path-A trial-matrix PBO when available (from lab/scripts/run_pbo_path_a.py)
    try:
        from lab.validation.trial_matrix import load_latest_pbo

        latest = load_latest_pbo()
        if latest and latest.get("ok") and (latest.get("pbo") or {}).get("ok"):
            bundle["pbo"] = latest["pbo"]
            bundle["pbo_source"] = "lab/research/validation/pbo_path_a_latest.json"
            bundle["pbo_matrix_meta"] = latest.get("matrix_meta")
            if latest.get("dsr_primary"):
                bundle["dsr_from_trial_matrix"] = latest["dsr_primary"]
            if latest.get("effective_trials"):
                bundle["effective_trials"] = latest["effective_trials"]
    except Exception:
        pass
    return bundle
