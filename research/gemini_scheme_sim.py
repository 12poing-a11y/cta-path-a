# -*- coding: utf-8 -*-
"""Full Gemini/HTML upgrade-scheme design + closed-loop shadow simulation.

Simulates the *intended* P0→P2 architecture as a research sandbox on top of
Path-A historical equity / trades. Does not write paper_book, seats, or
position_rules.

Layers
------
P0 Dual-Track TVS : downside HV target vol + IV warn + tolerance band
                   (portfolio overlay + per-symbol overlay)
P1 VRP sleeve     : when IV>>HV, approximate short-var proxy PnL on optionable
                   codes (research proxy — not exchange option fills)
P2 Carry soft-wt  : soft scale Path-A day PnL by front-next carry alignment
                   when gaps available; else neutral
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

from research.gemini_tvs_per_symbol import (
    calibrate_to_book,
    reconstruct_symbol_day_pnls,
    run_per_symbol_tvs,
)
from research.gemini_tvs_shadow import (
    downside_hv_ann,
    iv_percentile,
    load_iv_series,
    max_dd_pct,
    run_independent_oos,
    run_tvs_overlay,
    split_equity_curve,
)

SCHEME_VERSION = "gemini_scheme_sim_v1"


def scheme_design() -> dict[str, Any]:
    """Authoritative design map vs HTML cta_path_a.html framework."""
    return {
        "scheme_version": SCHEME_VERSION,
        "source": "Gemini/HTML《从趋势单腿到波动率协同》",
        "governance": {
            "writes_paper_book": False,
            "writes_seats": False,
            "writes_position_rules": False,
            "mode": "closed_loop_shadow_simulation",
        },
        "layers": {
            "P0_tvs": {
                "intent": "Downside-HV TVS + IV forward warn + ±5% band replace static ATR caps",
                "html_targets": [
                    "position_rules.py",
                    "portfolio/risk_contribution.py",
                    "regime_enable.json",
                ],
                "sim_implementation": [
                    "portfolio equity overlay (run_tvs_overlay)",
                    "per-symbol overlay (run_per_symbol_tvs)",
                    "independent IS/OOS freeze",
                ],
                "known_gaps_vs_html": [
                    "does_not_recompute_lots_from_ATR_budget",
                    "does_not_write_regime_enable",
                    "iv_from_akshare_cache_not_gamma_wall_atm_chain",
                    "max_leverage_capped_at_1.0_no_upscale",
                ],
            },
            "P1_vrp_sleeve": {
                "intent": "IV-RV premium → short-vol shadow sleeve + delta-neutral narrative",
                "html_targets": ["vol_engine.py", "option_hedge.py", "proxy_vol_vrp"],
                "sim_implementation": [
                    "variance_risk_proxy_pnl = notional * (iv^2 - rv^2) on warn days",
                    "opportunity counting only when IV pctile high",
                ],
                "known_gaps_vs_html": [
                    "no_real_straddle_fills",
                    "no_greeks_rebalance_at_0.15_delta",
                    "no_bid_ask_costs",
                    "proxy_notional_is_research_assumption",
                ],
            },
            "P2_carry_friction": {
                "intent": "Roll yield soft weight + dynamic slippage",
                "html_targets": ["basis_data.py", "path_a_filters.py", "research/execution"],
                "sim_implementation": [
                    "soft_scale Path-A day pnl by carry_alignment when gaps loadable",
                    "static_slip_stress_scenario only (no depth model)",
                ],
                "known_gaps_vs_html": [
                    "no_dynamic_slippage_from_OI_depth",
                    "no_path_a_filters_weight_injection",
                    "carry_may_be_unavailable",
                ],
            },
        },
        "acceptance_html": {
            "P0": "turnover/cost down; max DD not above 3.3% on L1 ablation",
            "P1": "shadow Sharpe>1 and corr(Path-A)<0.25",
            "P2": "Locked OOS net + PBO<0.30",
        },
    }


def _equity_metrics(curve: Sequence[float]) -> dict[str, float]:
    if not curve or curve[0] <= 0:
        return {"ret_pct": 0.0, "max_dd_pct": 0.0, "equity_end": 0.0}
    ret = 100.0 * (curve[-1] / curve[0] - 1.0)
    return {
        "ret_pct": round(ret, 3),
        "max_dd_pct": max_dd_pct(curve),
        "equity_start": round(float(curve[0]), 2),
        "equity_end": round(float(curve[-1]), 2),
    }


def simulate_p1_vrp_sleeve(
    equity_curve: Sequence[dict],
    *,
    root: Path,
    notional_per_hit: float = 20_000.0,
    iv_warn_pctile: float = 0.90,
    rv_window: int = 20,
) -> dict[str, Any]:
    """Research proxy for short-var sleeve — not exchange option execution."""
    root = Path(root)
    rows = [r for r in equity_curve if r.get("date")]
    codes: set[str] = set()
    for r in rows:
        for c in r.get("codes") or []:
            codes.add(str(c).upper())
    iv_map = {c: load_iv_series(root, c) for c in sorted(codes)}

    from desk.local_bars import load_local_bars

    rets: dict[str, list[tuple[str, float]]] = {}
    for c in codes:
        bars, _ = load_local_bars(root, c)
        xs = []
        prev = None
        for b in bars:
            d = str(b.get("date") or "")[:10]
            px = b.get("close")
            try:
                px = float(px)
            except (TypeError, ValueError):
                continue
            if len(d) != 10 or px <= 0:
                continue
            if prev:
                xs.append((d, px / prev - 1.0))
            prev = px
        rets[c] = xs

    eq0 = float(rows[0].get("equity") or 200000) - float(rows[0].get("pnl") or 0)
    if eq0 <= 0:
        eq0 = 200000.0
    eq = eq0
    curve = [eq]
    n_opp = 0
    n_pnl_days = 0
    day_pnls = []

    for r in rows:
        day = str(r["date"])[:10]
        held = [str(c).upper() for c in (r.get("codes") or [])]
        pnl = 0.0
        for c in held:
            series = iv_map.get(c) or {}
            hist_days = [d for d in series if d <= day]
            if len(hist_days) < 20:
                continue
            iv = series[hist_days[-1]]
            pct = iv_percentile([series[d] for d in hist_days[-60:]], iv)
            hist_r = [x for d, x in rets.get(c, []) if d <= day]
            rv = downside_hv_ann(hist_r, window=rv_window)
            # use full HV approx: std of last window * sqrt(252)
            if len(hist_r) >= rv_window:
                w = hist_r[-rv_window:]
                mu = sum(w) / len(w)
                var = sum((x - mu) ** 2 for x in w) / max(len(w) - 1, 1)
                rv_full = math.sqrt(max(var, 0.0)) * math.sqrt(252.0)
            else:
                rv_full = rv
            if pct is None or rv_full is None:
                continue
            if pct >= iv_warn_pctile and iv > rv_full:
                n_opp += 1
                # short variance proxy daily accrual ~ notional*(iv^2 - rv^2)/252
                pnl += float(notional_per_hit) * (iv * iv - rv_full * rv_full) / 252.0
                n_pnl_days += 1
        eq += pnl
        curve.append(eq)
        day_pnls.append({"date": day, "pnl": round(pnl, 2)})

    m = _equity_metrics(curve)
    return {
        "ok": True,
        "layer": "P1_vrp_sleeve_proxy",
        "n_opportunity_hits": n_opp,
        "n_days_with_pnl": n_pnl_days,
        "notional_per_hit": notional_per_hit,
        "metrics": m,
        "note": "variance_proxy_only_not_option_fills",
        "day_pnls_tail": day_pnls[-5:],
    }


def simulate_p2_carry_soft(
    equity_curve: Sequence[dict],
    *,
    root: Path,
    scale_strength: float = 0.25,
) -> dict[str, Any]:
    """Soft-scale Path-A day PnL by carry alignment when gaps available."""
    root = Path(root)
    rows = [r for r in equity_curve if r.get("date")]
    carry_ok = False
    gaps_by_code: dict[str, float] = {}
    try:
        from desk.regime_board import load_carry_gaps

        gaps = load_carry_gaps(root) or {}
        # expect mapping code -> gap fraction or similar
        if isinstance(gaps, dict):
            for k, v in gaps.items():
                try:
                    gaps_by_code[str(k).upper()] = float(v)
                    carry_ok = True
                except (TypeError, ValueError):
                    continue
    except Exception:
        carry_ok = False

    eq0 = float(rows[0].get("equity") or 200000) - float(rows[0].get("pnl") or 0)
    if eq0 <= 0:
        eq0 = 200000.0
    eq_base = eq0
    eq_carry = eq0
    c_base = [eq_base]
    c_carry = [eq_carry]
    n_scaled = 0

    for r in rows:
        pnl = float(r.get("pnl") or 0.0)
        eq_base += pnl
        c_base.append(eq_base)
        factor = 1.0
        if carry_ok and (r.get("codes") or []):
            # If average gap sign aligns with holding (unknown direction),
            # use mild dampening when |gap| extreme — research soft prior.
            vals = [gaps_by_code[c] for c in r["codes"] if str(c).upper() in gaps_by_code]
            if vals:
                avg = sum(vals) / len(vals)
                # extreme carry → reduce risk (stress), mild → slight boost to pnl keep
                if abs(avg) >= 0.01:
                    factor = max(0.5, 1.0 - float(scale_strength))
                    n_scaled += 1
                else:
                    factor = 1.0 + 0.05 * float(scale_strength)
        eq_carry += pnl * factor
        c_carry.append(eq_carry)

    return {
        "ok": True,
        "layer": "P2_carry_soft",
        "carry_data_available": carry_ok,
        "n_days_scaled": n_scaled,
        "baseline": _equity_metrics(c_base),
        "carry_soft": _equity_metrics(c_carry),
        "delta_ret_pct_pts": round(
            _equity_metrics(c_carry)["ret_pct"] - _equity_metrics(c_base)["ret_pct"], 3
        ),
        "known_gap": "static_soft_scale_not_dynamic_slippage_model",
    }


def combine_sleeves(
    equity_curve: Sequence[dict],
    *,
    p0: dict,
    p1: dict,
    p2: dict,
) -> dict[str, Any]:
    """Stack P0 per-symbol (or portfolio) TVS PnL path + P1 proxy + P2 factor.

    Practical combo used for audit:
    - start from official Path-A equity
    - replace with P0 per-symbol TVS equity path when available
    - add P1 cumulative proxy PnL
    - report P2 as alternate soft path (not double-counted into combo by default)
    """
    rows = [r for r in equity_curve if r.get("date")]
    base0 = float(rows[0].get("equity") or 200000) - float(rows[0].get("pnl") or 0)
    if base0 <= 0:
        base0 = 200000.0

    # Reconstruct day pnl from baseline curve
    base_pnls = [float(r.get("pnl") or 0) for r in rows]
    # P0: use reported end equity ratio path if present
    p0_end = ((p0.get("tvs_shadow") or {}).get("equity_end"))
    p0_start = ((p0.get("tvs_shadow") or {}).get("equity_start")) or base0
    if p0_end is None:
        p0_mult = 1.0
        p0_path_ret = sum(base_pnls)
    else:
        p0_path_ret = float(p0_end) - float(p0_start)

    p1_end = ((p1.get("metrics") or {}).get("equity_end"))
    p1_start = ((p1.get("metrics") or {}).get("equity_start")) or base0
    p1_extra = (float(p1_end) - float(p1_start)) if p1_end is not None else 0.0

    combo_end = float(p0_start) + p0_path_ret + p1_extra
    base_end = base0 + sum(base_pnls)
    return {
        "baseline_ret_pct": round(100.0 * (base_end / base0 - 1.0), 3),
        "combo_p0_p1_ret_pct": round(100.0 * (combo_end / base0 - 1.0), 3),
        "p0_path_pnl": round(p0_path_ret, 2),
        "p1_extra_pnl": round(p1_extra, 2),
        "p2_alt_delta_ret_pct_pts": p2.get("delta_ret_pct_pts"),
        "note": "P2 reported separately to avoid double-scaling P0 path",
    }


def run_full_scheme_simulation(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or ".")
    hb = json.loads((root / "historical_backtest_latest.json").read_text(encoding="utf-8"))
    curve = hb.get("equity_curve") or []
    design = scheme_design()

    # P0 portfolio overlay full + OOS
    p0_port_full = run_tvs_overlay(curve, root=root, target_vol=0.15, tolerance_band=0.05)
    p0_port_oos = run_independent_oos(curve, root=root, is_frac=0.60)

    # P0 per-symbol
    calendar = [str(r["date"])[:10] for r in curve]
    raw = reconstruct_symbol_day_pnls(hb.get("closed_pnls") or [], root=root, calendar=calendar)
    calibrated = calibrate_to_book(raw, curve)
    p0_sym_full = run_per_symbol_tvs(
        curve, calibrated, root=root, target_vol=0.15, tolerance_band=0.05,
    )
    # per-symbol OOS quick: freeze 0.15/0.05
    is_rows, oos_rows, split = split_equity_curve(curve, is_frac=0.60)
    is_days = {str(r["date"])[:10] for r in is_rows}
    oos_days = {str(r["date"])[:10] for r in oos_rows}
    p0_sym_oos = run_per_symbol_tvs(
        oos_rows,
        {d: calibrated[d] for d in oos_days if d in calibrated},
        root=root,
        target_vol=0.15,
        tolerance_band=0.05,
    )

    p1 = simulate_p1_vrp_sleeve(curve, root=root)
    p2 = simulate_p2_carry_soft(curve, root=root)
    combo = combine_sleeves(curve, p0=p0_sym_full, p1=p1, p2=p2)

    return {
        "ok": True,
        "mode": "gemini_full_scheme_simulation",
        "scheme_version": SCHEME_VERSION,
        "design": design,
        "path_a_meta": {
            "start": hb.get("start"),
            "end": hb.get("end"),
            "ret_pct": hb.get("ret_pct"),
            "max_dd_pct": hb.get("max_dd_pct"),
        },
        "simulation": {
            "P0_portfolio": {
                "full": {
                    "baseline": p0_port_full.get("baseline"),
                    "tvs_shadow": p0_port_full.get("tvs_shadow"),
                    "delta": p0_port_full.get("delta"),
                },
                "oos": p0_port_oos.get("oos_eval"),
                "oos_acceptance": p0_port_oos.get("oos_acceptance"),
                "frozen_params": p0_port_oos.get("frozen_params"),
            },
            "P0_per_symbol": {
                "full": {
                    "baseline": p0_sym_full.get("baseline"),
                    "tvs_shadow": p0_sym_full.get("tvs_shadow"),
                    "delta": p0_sym_full.get("delta"),
                    "tracking": p0_sym_full.get("tracking"),
                },
                "oos": {
                    "baseline": p0_sym_oos.get("baseline"),
                    "tvs_shadow": p0_sym_oos.get("tvs_shadow"),
                    "delta": p0_sym_oos.get("delta"),
                },
                "split": split,
            },
            "P1_vrp_sleeve": p1,
            "P2_carry_soft": p2,
            "combo_p0_p1": combo,
        },
    }
