# -*- coding: utf-8 -*-
"""V1.3 arbitrage shadow monitor (research only).

Answers: why the system did not trade, and whether blocked signals were
good opportunities ex-post. Does not write paper_book or seats.

Dual paths per pair:
- gated: risk gate + cointegration must PASS before a suggested entry
- counterfactual: same signal/sizing without the gate (attribution only)

Counterfactual PnL uses subsequent prices for audit; it must never feed
live sizing or Path-A.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from research.arbitrage_volatility import (
    evaluate_risk_gate,
    pair_correlation,
    rolling_cointegration,
    rolling_spread,
    size_pair_position,
    spread_risk_metrics,
)

MODEL_VERSION = "arb_shadow_v1.3"
STRATEGY_ID = "pair_spread_z_fade"


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def assess_bar_data_quality(
    row: dict,
    *,
    prev_row: dict | None = None,
    roll_gap_pct: float = 0.05,
) -> dict[str, Any]:
    """Flag missing prices/OI and suspicious overnight gaps (roll proxy)."""
    reasons: list[str] = []
    a = _finite(row.get("leg_a_close") or row.get("leg_a"))
    b = _finite(row.get("leg_b_close") or row.get("leg_b"))
    if a is None or b is None:
        reasons.append("missing_price")
    va = _finite(row.get("leg_a_volume"))
    vb = _finite(row.get("leg_b_volume"))
    if va is None or vb is None:
        reasons.append("missing_volume")
    elif va <= 0 or vb <= 0:
        reasons.append("zero_volume")
    oa = _finite(row.get("leg_a_oi"))
    ob = _finite(row.get("leg_b_oi"))
    if oa is None or ob is None:
        reasons.append("missing_oi")
    if prev_row is not None and a is not None and b is not None:
        pa = _finite(prev_row.get("leg_a_close") or prev_row.get("leg_a"))
        pb = _finite(prev_row.get("leg_b_close") or prev_row.get("leg_b"))
        if pa and pb and pa > 0 and pb > 0:
            gap = max(abs(a / pa - 1.0), abs(b / pb - 1.0))
            if gap >= float(roll_gap_pct):
                reasons.append("suspected_roll_or_gap")
    status = "OK" if not reasons else ("BLOCK_DQ" if "missing_price" in reasons else "WATCH")
    return {"status": status, "reasons": reasons}


def _suggested_size(
    *,
    vol: dict,
    beta: float | None,
    spec_a: dict,
    spec_b: dict,
    risk_budget_yuan: float,
    max_a_contracts: int,
    gate: dict,
) -> dict[str, Any]:
    vol_pts = vol.get("vol_ewma") or vol.get("es_abs") or vol.get("vol_long") or vol.get("spread_atr")
    return size_pair_position(
        risk_budget_yuan=risk_budget_yuan,
        spread_vol_points=vol_pts,
        multiplier_a=float(spec_a["mult"]),
        multiplier_b=float(spec_b["mult"]),
        hedge_ratio=beta,
        max_a_contracts=max_a_contracts,
        gate=gate,
    )


def _forward_pnl(
    rows_by_date: dict[str, dict],
    days: Sequence[str],
    start_idx: int,
    *,
    pos: int,
    qa: int,
    qb: int,
    mult_a: float,
    mult_b: float,
    z_exit: float,
    max_hold: int,
    z_series: dict[str, float | None],
) -> dict[str, Any]:
    """Ex-post attribution from entry day close to exit/z_exit/max_hold."""
    if start_idx >= len(days) - 1 or qa <= 0 or qb <= 0 or pos == 0:
        return {"ok": False, "pnl_yuan": None, "hold_days": 0, "exit_date": None}
    entry_day = days[start_idx]
    entry = rows_by_date[entry_day]
    ea = _finite(entry.get("leg_a_close") or entry.get("leg_a"))
    eb = _finite(entry.get("leg_b_close") or entry.get("leg_b"))
    if ea is None or eb is None:
        return {"ok": False, "pnl_yuan": None, "hold_days": 0, "exit_date": None}
    end_i = min(len(days) - 1, start_idx + max_hold)
    exit_i = end_i
    for j in range(start_idx + 1, end_i + 1):
        z = z_series.get(days[j])
        if z is not None and abs(z) <= z_exit:
            exit_i = j
            break
    ex = rows_by_date[days[exit_i]]
    xa = _finite(ex.get("leg_a_close") or ex.get("leg_a"))
    xb = _finite(ex.get("leg_b_close") or ex.get("leg_b"))
    if xa is None or xb is None:
        return {"ok": False, "pnl_yuan": None, "hold_days": 0, "exit_date": None}
    da, db = xa - ea, xb - eb
    if pos > 0:
        pnl = qa * da * mult_a + (-qb) * db * mult_b
    else:
        pnl = (-qa) * da * mult_a + qb * db * mult_b
    return {
        "ok": True,
        "pnl_yuan": round(pnl, 2),
        "hold_days": exit_i - start_idx,
        "exit_date": days[exit_i],
        "note": "ex_post_attribution_only",
    }


def monitor_pair(
    rows: Sequence[dict],
    *,
    pair_id: str,
    spec_a: dict,
    spec_b: dict,
    start: str | None = None,
    end: str | None = None,
    z_enter: float = 1.5,
    z_exit: float = 0.5,
    lookback: int = 60,
    coint_lookback: int = 120,
    risk_budget_yuan: float = 20_000.0,
    max_a_contracts: int = 5,
    max_hold: int = 10,
    require_cointegration: bool = True,
    max_half_life: float = 60.0,
) -> dict[str, Any]:
    """Build daily shadow decisions + dual-path attribution for one pair."""
    aligned = list(rows)
    spreads = rolling_spread(aligned, lookback=lookback, min_observations=max(30, lookback // 2))
    coints = rolling_cointegration(
        aligned,
        lookback=coint_lookback,
        min_observations=max(60, coint_lookback // 2),
        max_half_life=max_half_life,
    )
    coint_by = {r["date"]: r for r in coints}
    by_spread = {r["date"]: r for r in spreads}
    by_row = {str(r["date"])[:10]: r for r in aligned}
    days = [r["date"] for r in spreads]
    if start:
        days = [d for d in days if d >= start]
    if end:
        days = [d for d in days if d <= end]

    # Precompute z for counterfactual exits
    z_series: dict[str, float | None] = {}
    for d in [r["date"] for r in spreads]:
        hist = [r for r in spreads if r["date"] <= d]
        z_series[d] = spread_risk_metrics(hist).get("spread_z")

    decisions: list[dict] = []
    reason_counts: Counter[str] = Counter()
    dq_counts: Counter[str] = Counter()
    n_signal = n_pass = n_block = n_watch = 0
    cf_pnls: list[float] = []
    gated_would_trade_pnls: list[float] = []

    prev_row = None
    for i, day in enumerate(days):
        last = by_spread[day]
        raw = by_row.get(day) or {}
        merged = {**raw, **last}
        dq = assess_bar_data_quality(merged, prev_row=prev_row)
        for r in dq["reasons"]:
            dq_counts[r] += 1

        hist = [r for r in spreads if r["date"] <= day]
        vol = spread_risk_metrics(hist)
        ok_hist = [r for r in hist if r.get("ok")]
        ca = [float(r["leg_a"]) for r in ok_hist]
        cb = [float(r["leg_b"]) for r in ok_hist]
        corr = pair_correlation(ca, cb, window=lookback)
        beta = last.get("hedge_ratio")
        coint = coint_by.get(day) or {"ok": False, "reason": "missing"}
        gate = evaluate_risk_gate(
            volatility=vol,
            correlation=corr,
            hedge_ratio=beta,
            cointegration=coint,
            require_cointegration=require_cointegration,
            max_half_life=max_half_life,
        )
        z = vol.get("spread_z")
        signal = None
        if last.get("ok") and z is not None and abs(z) >= z_enter:
            signal = "fade_short_spread" if z >= z_enter else "fade_long_spread"
            n_signal += 1

        gate_status = "PASS" if gate.get("allow_new_risk") else "BLOCK"
        if dq["status"] == "WATCH" and gate_status == "PASS":
            gate_status = "WATCH"
        if dq["status"] == "BLOCK_DQ":
            gate_status = "BLOCK"
            gate = dict(gate)
            reasons = list(gate.get("reasons") or [])
            if "data_quality_block" not in reasons:
                reasons.append("data_quality_block")
            gate["reasons"] = reasons
            gate["allow_new_risk"] = False

        sized_gated = _suggested_size(
            vol=vol, beta=beta, spec_a=spec_a, spec_b=spec_b,
            risk_budget_yuan=risk_budget_yuan, max_a_contracts=max_a_contracts,
            gate=gate,
        )
        sized_cf = _suggested_size(
            vol=vol, beta=beta, spec_a=spec_a, spec_b=spec_b,
            risk_budget_yuan=risk_budget_yuan, max_a_contracts=max_a_contracts,
            gate={"allow_new_risk": True},
        )

        block_reasons = list(gate.get("reasons") or [])
        for br in block_reasons:
            reason_counts[br] += 1

        counterfactual = None
        gated_attr = None
        if signal is not None and sized_cf.get("ok"):
            pos = -1 if z >= z_enter else 1
            counterfactual = _forward_pnl(
                by_row, days, i,
                pos=pos,
                qa=int(sized_cf["contracts_a"]),
                qb=int(sized_cf["contracts_b"]),
                mult_a=float(spec_a["mult"]),
                mult_b=float(spec_b["mult"]),
                z_exit=z_exit,
                max_hold=max_hold,
                z_series=z_series,
            )
            if counterfactual.get("ok") and counterfactual.get("pnl_yuan") is not None:
                cf_pnls.append(float(counterfactual["pnl_yuan"]))
            if sized_gated.get("ok") and gate.get("allow_new_risk"):
                n_pass += 1
                gated_attr = _forward_pnl(
                    by_row, days, i,
                    pos=pos,
                    qa=int(sized_gated["contracts_a"]),
                    qb=int(sized_gated["contracts_b"]),
                    mult_a=float(spec_a["mult"]),
                    mult_b=float(spec_b["mult"]),
                    z_exit=z_exit,
                    max_hold=max_hold,
                    z_series=z_series,
                )
                if gated_attr.get("ok") and gated_attr.get("pnl_yuan") is not None:
                    gated_would_trade_pnls.append(float(gated_attr["pnl_yuan"]))
            else:
                n_block += 1
        elif signal is not None:
            n_block += 1

        if gate_status == "WATCH":
            n_watch += 1

        decisions.append({
            "timestamp": day,
            "symbol": pair_id,
            "strategy_id": STRATEGY_ID,
            "model_version": MODEL_VERSION,
            "spread_z": z,
            "signal": signal,
            "hedge_ratio": beta,
            "correlation": corr,
            "vol_ewma": vol.get("vol_ewma"),
            "vol_expansion_ratio": vol.get("vol_expansion_ratio"),
            "es_abs": vol.get("es_abs"),
            "cointegration_ok": bool(coint.get("ok")),
            "half_life": coint.get("half_life"),
            "break_flag": bool(coint.get("break_flag")),
            "coint_reason": coint.get("reason"),
            "risk_budget": risk_budget_yuan,
            "suggested_lots": {
                "gated": {
                    "a": sized_gated.get("contracts_a"),
                    "b": sized_gated.get("contracts_b"),
                    "status": sized_gated.get("status"),
                },
                "counterfactual": {
                    "a": sized_cf.get("contracts_a"),
                    "b": sized_cf.get("contracts_b"),
                    "status": sized_cf.get("status"),
                },
            },
            "gate_status": gate_status if signal else ("IDLE" if last.get("ok") else "NO_SPREAD"),
            "block_reason": block_reasons,
            "counterfactual_pnl": counterfactual,
            "gated_attribution_pnl": gated_attr,
            "data_quality_status": dq["status"],
            "data_quality_reasons": dq["reasons"],
            "mode": "shadow_only",
        })
        prev_row = merged

    def _sum(xs: list[float]) -> float:
        return round(sum(xs), 2)

    blocked_signal_cf = [
        d for d in decisions
        if d.get("signal") and d.get("gate_status") == "BLOCK" and (d.get("counterfactual_pnl") or {}).get("ok")
    ]
    blocked_cf_pnls = [float(d["counterfactual_pnl"]["pnl_yuan"]) for d in blocked_signal_cf]

    return {
        "ok": True,
        "pair": pair_id,
        "model_version": MODEL_VERSION,
        "window": {"start": days[0] if days else None, "end": days[-1] if days else None},
        "n_days": len(days),
        "n_signal": n_signal,
        "n_pass": n_pass,
        "n_block": n_block,
        "n_watch": n_watch,
        "block_reason_counts": dict(reason_counts),
        "data_quality_counts": dict(dq_counts),
        "dual_path": {
            "gated_signal_pnl_sum": _sum(gated_would_trade_pnls),
            "gated_signal_n": len(gated_would_trade_pnls),
            "counterfactual_all_signal_pnl_sum": _sum(cf_pnls),
            "counterfactual_all_signal_n": len(cf_pnls),
            "blocked_only_counterfactual_pnl_sum": _sum(blocked_cf_pnls),
            "blocked_only_n": len(blocked_cf_pnls),
            "blocked_only_mean_pnl": round(sum(blocked_cf_pnls) / len(blocked_cf_pnls), 2) if blocked_cf_pnls else None,
        },
        "decisions": decisions,
    }


def append_decision_ledger(
    path: Path,
    decisions: Sequence[dict],
) -> int:
    """Append-only JSONL ledger; never overwrite prior model decisions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for row in decisions:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def summarize_universe(pair_reports: Sequence[dict]) -> dict[str, Any]:
    reason = Counter()
    dq = Counter()
    dual = {
        "gated_signal_pnl_sum": 0.0,
        "counterfactual_all_signal_pnl_sum": 0.0,
        "blocked_only_counterfactual_pnl_sum": 0.0,
        "n_signal": 0,
        "n_pass": 0,
        "n_block": 0,
    }
    slim_pairs = []
    for r in pair_reports:
        for k, v in (r.get("block_reason_counts") or {}).items():
            reason[k] += int(v)
        for k, v in (r.get("data_quality_counts") or {}).items():
            dq[k] += int(v)
        dp = r.get("dual_path") or {}
        dual["gated_signal_pnl_sum"] += float(dp.get("gated_signal_pnl_sum") or 0)
        dual["counterfactual_all_signal_pnl_sum"] += float(dp.get("counterfactual_all_signal_pnl_sum") or 0)
        dual["blocked_only_counterfactual_pnl_sum"] += float(dp.get("blocked_only_counterfactual_pnl_sum") or 0)
        dual["n_signal"] += int(r.get("n_signal") or 0)
        dual["n_pass"] += int(r.get("n_pass") or 0)
        dual["n_block"] += int(r.get("n_block") or 0)
        slim_pairs.append({k: v for k, v in r.items() if k != "decisions"})
    for k in ("gated_signal_pnl_sum", "counterfactual_all_signal_pnl_sum", "blocked_only_counterfactual_pnl_sum"):
        dual[k] = round(dual[k], 2)
    return {
        "mode": "shadow_v1_3_monitor",
        "model_version": MODEL_VERSION,
        "disclaimer": (
            "V1.3 影子监控：只回答为何拦截与拦截后的反事实表现；"
            "counterfactual 为事后归因，不写 paper_book / seats，不自动开平。"
        ),
        "block_reason_counts": dict(reason),
        "data_quality_counts": dict(dq),
        "dual_path_totals": dual,
        "pairs": slim_pairs,
    }
