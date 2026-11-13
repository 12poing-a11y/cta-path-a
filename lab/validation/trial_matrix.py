# -*- coding: utf-8 -*-
"""Build compact T×K Path-A trial return matrices for PBO (research only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
OUT_DIR = LAB / "research" / "validation"
LATEST = OUT_DIR / "pbo_path_a_latest.json"


def path_a_trial_specs(root: Path | None = None) -> list[dict[str, Any]]:
    """Current + archived + small stop/rr neighborhood (deduped)."""
    root = root or ROOT
    rules = json.loads((root / "execution_rules.json").read_text(encoding="utf-8"))
    uni = json.loads((root / "universe.json").read_text(encoding="utf-8"))
    sel = uni.get("selection") or {}
    specs: list[dict[str, Any]] = []

    def add(*, stop: float, rr: float, r20: float, r60: float, label: str) -> None:
        key = (round(stop, 4), round(rr, 4), round(r20, 4), round(r60, 4))
        if any(
            (round(s["stop_atr_mult"], 4), round(s["reward_rr"], 4), round(s["min_r20"], 4), round(s["min_r60"], 4))
            == key
            for s in specs
        ):
            return
        specs.append(
            {
                "trial_id": f"s{stop:g}_rr{rr:g}_m{r20:g}_{r60:g}",
                "label": label,
                "stop_atr_mult": float(stop),
                "reward_rr": float(rr),
                "min_r20": float(r20),
                "min_r60": float(r60),
            }
        )

    cur_stop = float(rules.get("stop_atr_mult") or sel.get("stop_atr_mult") or 0.8)
    cur_rr = float(rules.get("reward_rr") or sel.get("reward_rr") or 2.0)
    cur_r20 = float(rules.get("min_r20_pct") or sel.get("min_r20_pct") or uni.get("min_r20_pct") or 4.0)
    cur_r60 = float(rules.get("min_r60_pct") or sel.get("min_r60_pct") or uni.get("min_r60_pct") or 6.0)
    add(stop=cur_stop, rr=cur_rr, r20=cur_r20, r60=cur_r60, label="current")

    for row in rules.get("archived_params") or []:
        if not isinstance(row, dict):
            continue
        add(
            stop=float(row.get("stop_atr_mult") or cur_stop),
            rr=float(row.get("reward_rr") or cur_rr),
            r20=float(row.get("min_r20_pct") or cur_r20),
            r60=float(row.get("min_r60_pct") or cur_r60),
            label=str(row.get("label") or "archived"),
        )

    # Neighborhood around current (keeps K modest ~10–20)
    for stop in (0.8, 1.0, 1.2):
        for rr in (1.5, 2.0, 2.5):
            add(stop=stop, rr=rr, r20=cur_r20, r60=cur_r60, label="grid")
    for r20, r60 in ((3.0, 5.0), (4.0, 6.0), (5.0, 8.0)):
        add(stop=cur_stop, rr=cur_rr, r20=r20, r60=r60, label="mom_grid")

    return specs


def _curve_to_dated_returns(curve: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    prev = None
    for row in curve or []:
        if not isinstance(row, dict):
            continue
        d = str(row.get("date") or "")[:10]
        try:
            eq = float(row.get("equity"))
        except (TypeError, ValueError):
            continue
        if prev not in (None, 0) and d:
            out[d] = eq / float(prev) - 1.0
        prev = eq
    return out


def build_trial_return_matrix(
    *,
    simulate_fn,
    base_cfg: dict[str, Any],
    pack,
    mode: str = "base",
    specs: list[dict[str, Any]] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Run each trial on the same pack; keep only aligned daily returns (compact)."""
    root = root or ROOT
    specs = specs or path_a_trial_specs(root)
    dated: dict[str, dict[str, float]] = {}
    kpi_rows: list[dict[str, Any]] = []
    for spec in specs:
        trial_cfg = {
            **base_cfg,
            "stop_atr_mult": spec["stop_atr_mult"],
            "reward_rr": spec["reward_rr"],
            "min_r20": spec["min_r20"],
            "min_r60": spec["min_r60"],
            "cost_scenario": "base",
            "slippage_ticks": base_cfg.get("slippage_ticks"),
        }
        out = simulate_fn(trial_cfg, mode, pack=pack)
        tid = spec["trial_id"]
        if not out.get("ok"):
            kpi_rows.append({**spec, "ok": False, "error": out.get("error")})
            continue
        dated[tid] = _curve_to_dated_returns(out.get("equity_curve") or [])
        kpi_rows.append(
            {
                **spec,
                "ok": True,
                "ret_pct": out.get("ret_pct"),
                "max_dd_pct": out.get("max_dd_pct"),
                "cost_yuan": out.get("cost_yuan"),
                "closed_trades": out.get("closed_trades"),
                "sharpe_hint": None,
            }
        )

    names = [s["trial_id"] for s in specs if s["trial_id"] in dated]
    if len(names) < 2:
        return {
            "ok": False,
            "error": "need_at_least_2_successful_trials",
            "trials": kpi_rows,
            "n_trials": len(names),
        }
    dates = sorted(d for d in next(iter(dated.values())) if all(d in dated[n] for n in names))
    matrix = [[dated[n][d] for n in names] for d in dates]
    return {
        "ok": True,
        "schema": "cta-pbo-trial-matrix-v1",
        "mode": mode,
        "n_obs": len(dates),
        "n_trials": len(names),
        "trial_ids": names,
        "dates": dates,
        "returns": matrix,  # T×K
        "trials": kpi_rows,
        "bytes_estimate": len(dates) * len(names) * 8,
        "live_trading": False,
        "note": "Compact daily returns only; full equity curves not stored.",
    }


def compute_pbo_report(matrix_payload: dict[str, Any], *, n_groups: int = 8) -> dict[str, Any]:
    from lab.validation.dsr import deflated_sharpe_ratio
    from lab.validation.effective_trials import effective_trials, pairwise_corr
    from lab.validation.pbo import probability_of_backtest_overfitting
    from lab.validation.psr import probabilistic_sharpe_ratio

    if not matrix_payload.get("ok"):
        return {"ok": False, "error": matrix_payload.get("error"), "matrix": matrix_payload}
    mat = matrix_payload["returns"]
    names = matrix_payload["trial_ids"]
    pbo = probability_of_backtest_overfitting(mat, n_groups=n_groups)
    corr = pairwise_corr(mat)
    et = effective_trials(len(names), corr_matrix=corr)
    # DSR/PSR for "current"-like first trial if present else best IS sharpe trial by full-sample
    from lab.validation.returns import moments

    col_stats = []
    for j, name in enumerate(names):
        col = [row[j] for row in mat]
        m = moments(col)
        col_stats.append({"trial_id": name, "sharpe": m["sharpe"], "n": m["n"]})
    primary = names[0]
    primary_col = [row[names.index(primary)] for row in mat]
    psr = probabilistic_sharpe_ratio(primary_col)
    dsr = deflated_sharpe_ratio(
        primary_col,
        n_trials=len(names),
        mean_abs_corr=float(et.get("mean_abs_corr") or 0.0),
    )
    return {
        "ok": True,
        "schema": "cta-pbo-report-v1",
        "pbo": pbo,
        "effective_trials": et,
        "primary_trial_id": primary,
        "psr_primary": psr,
        "dsr_primary": dsr,
        "trial_sharpes": col_stats,
        "matrix_meta": {
            "n_obs": matrix_payload.get("n_obs"),
            "n_trials": matrix_payload.get("n_trials"),
            "bytes_estimate": matrix_payload.get("bytes_estimate"),
            "mode": matrix_payload.get("mode"),
        },
        "trials": matrix_payload.get("trials"),
        "live_trading": False,
        "auto_promote": False,
    }


def save_pbo_artifacts(report: dict[str, Any], matrix: dict[str, Any], root: Path | None = None) -> dict[str, str]:
    root = root or ROOT
    out_dir = root / "lab" / "research" / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = out_dir / "pbo_path_a_matrix.json"
    report_path = out_dir / "pbo_path_a_latest.json"
    # Store matrix separately; report embeds meta only (avoid huge duplication in latest)
    slim = {k: v for k, v in matrix.items() if k != "returns"}
    slim["returns_sha_hint"] = f"T={matrix.get('n_obs')}xK={matrix.get('n_trials')}"
    payload = {**report, "matrix_ref": "pbo_path_a_matrix.json", "matrix_meta_full": slim}
    matrix_path.write_text(json.dumps(matrix, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "matrix": str(matrix_path.relative_to(root)),
        "report": str(report_path.relative_to(root)),
    }


def load_latest_pbo(root: Path | None = None) -> dict[str, Any] | None:
    root = root or ROOT
    path = root / "lab" / "research" / "validation" / "pbo_path_a_latest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
