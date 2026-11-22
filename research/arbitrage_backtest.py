# -*- coding: utf-8 -*-
"""V1.2 shadow pair-spread backtest (research only).

- Signal at T close; fill at T+1 (open if present else close — CODE0 often lacks open).
- Costs: per-leg fee_yuan / fee_rate + slippage_ticks * tick * mult.
- Limit-move stress: skip new fills when |leg return| >= limit_pct.
- Controls: fixed_lots | spread_vol | spread_vol_gate | portfolio_mrc.
Does not write paper_book or Path-A seats.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from research.arbitrage_volatility import (
    align_pair_bars,
    contract_spec_from_universe_row,
    evaluate_risk_gate,
    pair_correlation,
    rolling_cointegration,
    rolling_spread,
    size_pair_position,
    spread_risk_metrics,
)


CONTROL_MODES = (
    "fixed_lots",
    "spread_vol",
    "spread_vol_gate",
    "portfolio_mrc",
)


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _max_dd_pct(equity: Sequence[float]) -> float:
    if not equity:
        return 0.0
    peak = float(equity[0])
    mdd = 0.0
    for e in equity:
        peak = max(peak, float(e))
        if peak > 0:
            mdd = max(mdd, (peak - float(e)) / peak)
    return mdd * 100.0


def round_trip_cost_yuan(
    *,
    spec_a: dict,
    spec_b: dict,
    contracts_a: int,
    contracts_b: int,
    px_a: float,
    px_b: float,
    slip_ticks: float = 1.0,
) -> float:
    """Approximate open+close costs for both legs (2 sides each)."""
    def leg_cost(spec: dict, qty: int, px: float) -> float:
        fee = abs(qty) * (
            float(spec["fee_yuan"])
            + abs(px) * float(spec["mult"]) * float(spec["fee_rate"])
        )
        slip = abs(qty) * float(slip_ticks) * float(spec["tick"]) * float(spec["mult"])
        return 2.0 * (fee + slip)  # open + close

    return leg_cost(spec_a, contracts_a, px_a) + leg_cost(spec_b, contracts_b, px_b)


def allocate_mrc_budgets(
    pair_ids: Sequence[str],
    pair_returns: dict[str, list[float]],
    *,
    total_budget: float,
    lookback: int = 60,
) -> dict[str, float]:
    """Inverse-vol risk budgets with correlation penalty (simple MRC proxy)."""
    vols: dict[str, float] = {}
    for pid in pair_ids:
        xs = pair_returns.get(pid) or []
        sample = xs[-lookback:]
        if len(sample) < 10:
            vols[pid] = 0.0
            continue
        mu = sum(sample) / len(sample)
        var = sum((x - mu) ** 2 for x in sample) / max(len(sample) - 1, 1)
        vols[pid] = math.sqrt(max(var, 0.0))
    # Weight ∝ 1/vol, zero if vol missing
    inv = {p: (1.0 / v if v > 1e-12 else 0.0) for p, v in vols.items()}
    s = sum(inv.values())
    if s <= 0:
        n = max(len(pair_ids), 1)
        return {p: float(total_budget) / n for p in pair_ids}
    return {p: float(total_budget) * inv[p] / s for p in pair_ids}


def _fill_prices(row: dict) -> tuple[float | None, float | None]:
    """Prefer open; fall back to close / rolling_spread leg_* aliases."""
    a = (
        _finite(row.get("leg_a_open"))
        or _finite(row.get("leg_a_close"))
        or _finite(row.get("leg_a"))
    )
    b = (
        _finite(row.get("leg_b_open"))
        or _finite(row.get("leg_b_close"))
        or _finite(row.get("leg_b"))
    )
    return a, b


def _limit_hit(prev: float | None, px: float | None, limit_pct: float) -> bool:
    if prev is None or px is None or prev <= 0:
        return False
    return abs(px / prev - 1.0) >= float(limit_pct) - 1e-12


def backtest_pair(
    rows: Sequence[dict],
    *,
    spec_a: dict,
    spec_b: dict,
    mode: str = "spread_vol_gate",
    start: str | None = None,
    end: str | None = None,
    z_enter: float = 1.5,
    z_exit: float = 0.5,
    lookback: int = 60,
    coint_lookback: int = 120,
    risk_budget_yuan: float = 20_000.0,
    fixed_lots_a: int = 1,
    max_a_contracts: int = 5,
    slip_ticks: float = 1.0,
    require_cointegration: bool = True,
    max_half_life: float = 60.0,
    signal_mode: str = "fade",
) -> dict[str, Any]:
    """Single-pair V1.2 research backtest.

    signal_mode:
    - fade: mean-reversion (short spread when z high) — default
    - follow: momentum / reverse of fade (long spread when z high)
    """
    if mode not in CONTROL_MODES:
        raise ValueError(f"unknown mode {mode}")
    if signal_mode not in ("fade", "follow"):
        raise ValueError("signal_mode must be fade or follow")
    aligned = list(rows)
    aligned_by = {str(r["date"])[:10]: r for r in aligned}
    spreads = rolling_spread(aligned, lookback=lookback, min_observations=max(30, lookback // 2))
    coints = rolling_cointegration(
        aligned,
        lookback=coint_lookback,
        min_observations=max(60, coint_lookback // 2),
        max_half_life=max_half_life,
    )
    coint_by = {r["date"]: r for r in coints}
    by = {r["date"]: r for r in spreads}
    days = [r["date"] for r in spreads]
    if start:
        days = [d for d in days if d >= start]
    if end:
        days = [d for d in days if d <= end]
    if len(days) < 40:
        return {"ok": False, "reason": "short_sample", "n_days": len(days), "mode": mode}

    pos = 0
    qa = qb = 0
    pending: dict | None = None  # signal to fill next bar
    cash = 0.0
    costs = 0.0
    equity = [0.0]
    day_pnl: dict[str, float] = {}
    trades = 0
    blocked = 0
    limit_skips = 0
    prev_a = prev_b = None
    fill_note = "next_open_else_close"

    for i, day in enumerate(days):
        last = by[day]
        a_px = last.get("leg_a")
        b_px = last.get("leg_b")
        # Mark-to-market existing position on close-to-close
        pnl = 0.0
        if pos != 0 and prev_a is not None and a_px is not None and b_px is not None:
            da = a_px - prev_a
            db = b_px - prev_b
            if pos > 0:
                pnl = qa * da * spec_a["mult"] + (-qb) * db * spec_b["mult"]
            else:
                pnl = (-qa) * da * spec_a["mult"] + qb * db * spec_b["mult"]
            cash += pnl
        day_pnl[day] = pnl
        equity.append(cash - costs)

        # Execute pending T-1 signal at today's fill (aligned row carries open when present)
        if pending is not None:
            fill_row = {**last, **(aligned_by.get(day) or {})}
            fa, fb = _fill_prices(fill_row)
            hit = (
                _limit_hit(prev_a, fa, spec_a["limit_pct"])
                or _limit_hit(prev_b, fb, spec_b["limit_pct"])
            )
            if fa is None or fb is None:
                limit_skips += 1
                pending = None
            elif hit:
                limit_skips += 1
                pending = None
            else:
                action = pending["action"]
                if action == "exit" and pos != 0:
                    costs += round_trip_cost_yuan(
                        spec_a=spec_a, spec_b=spec_b,
                        contracts_a=qa, contracts_b=qb,
                        px_a=fa, px_b=fb, slip_ticks=slip_ticks,
                    ) * 0.5  # already paid open; charge close half of round-trip approx
                    # Better: charge one side now. Use half of round_trip as close-only.
                    pos = qa = qb = 0
                elif action == "enter" and pos == 0:
                    qa = int(pending["contracts_a"])
                    qb = int(pending["contracts_b"])
                    pos = int(pending["pos"])
                    costs += round_trip_cost_yuan(
                        spec_a=spec_a, spec_b=spec_b,
                        contracts_a=qa, contracts_b=qb,
                        px_a=fa, px_b=fb, slip_ticks=slip_ticks,
                    ) * 0.5  # open half
                    trades += 1
                pending = None

        # Build diagnostics on history through today (no lookahead into future)
        hist = [r for r in spreads if r["date"] <= day]
        vol = spread_risk_metrics(hist)
        ok_hist = [r for r in hist if r.get("ok")]
        ca = [float(r["leg_a"]) for r in ok_hist]
        cb = [float(r["leg_b"]) for r in ok_hist]
        corr = pair_correlation(ca, cb, window=lookback)
        beta = last.get("hedge_ratio")
        coint = coint_by.get(day) or {"ok": False}
        use_gate = mode in ("spread_vol_gate", "portfolio_mrc")
        gate = evaluate_risk_gate(
            volatility=vol,
            correlation=corr,
            hedge_ratio=beta,
            cointegration=coint if require_cointegration else {"ok": True, "half_life": 1.0},
            require_cointegration=require_cointegration and use_gate,
            max_half_life=max_half_life,
        )
        z = vol.get("spread_z")

        # Schedule exits / entries for T+1 (do not fill same bar)
        if pending is None and z is not None and last.get("ok"):
            if pos != 0 and abs(z) <= z_exit:
                pending = {"action": "exit"}
            elif pos == 0 and abs(z) >= z_enter:
                if use_gate and not gate.get("allow_new_risk"):
                    blocked += 1
                else:
                    vol_pts = (
                        vol.get("vol_ewma")
                        or vol.get("es_abs")
                        or vol.get("vol_long")
                        or vol.get("spread_atr")
                    )
                    if mode == "fixed_lots":
                        qa_s = int(fixed_lots_a)
                        beta_f = float(beta) if beta is not None else 0.0
                        qb_s = int(round(abs(beta_f) * spec_a["mult"] / spec_b["mult"] * qa_s))
                        sized_ok = qa_s > 0 and qb_s > 0
                        contracts_a, contracts_b = qa_s, qb_s
                    else:
                        # spread_vol / gate / mrc share vol sizing; mrc budget injected by caller
                        sized = size_pair_position(
                            risk_budget_yuan=risk_budget_yuan,
                            spread_vol_points=vol_pts,
                            multiplier_a=spec_a["mult"],
                            multiplier_b=spec_b["mult"],
                            hedge_ratio=beta,
                            max_a_contracts=max_a_contracts,
                            gate={"allow_new_risk": True} if mode == "spread_vol" else gate,
                        )
                        sized_ok = bool(sized.get("ok"))
                        contracts_a = int(sized.get("contracts_a") or 0)
                        contracts_b = int(sized.get("contracts_b") or 0)
                    if sized_ok and contracts_a > 0 and contracts_b > 0:
                        if signal_mode == "fade":
                            pos_sign = -1 if z >= z_enter else 1
                        else:
                            pos_sign = 1 if z >= z_enter else -1
                        pending = {
                            "action": "enter",
                            "contracts_a": contracts_a,
                            "contracts_b": contracts_b,
                            "pos": pos_sign,
                        }
                    elif use_gate:
                        blocked += 1

        prev_a, prev_b = a_px, b_px

    net = cash - costs
    return {
        "ok": True,
        "mode": mode,
        "fill_policy": fill_note,
        "start": days[0],
        "end": days[-1],
        "n_days": len(days),
        "gross_pnl_yuan": round(cash, 2),
        "cost_yuan": round(costs, 2),
        "net_pnl_yuan": round(net, 2),
        "max_dd_pct": round(_max_dd_pct(equity), 3),
        "trades": trades,
        "blocked_entries": blocked,
        "limit_skips": limit_skips,
        "day_pnl": day_pnl,
        "require_cointegration": require_cointegration,
        "signal_mode": signal_mode,
    }


def backtest_universe(
    pair_bars: dict[str, Sequence[dict]],
    pair_specs: dict[str, tuple[dict, dict]],
    *,
    modes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    capital: float = 1_000_000.0,
    total_risk_budget: float = 80_000.0,
    focus_pairs: Sequence[str] | None = None,
    require_cointegration: bool = True,
    signal_mode: str = "fade",
) -> dict[str, Any]:
    """Run control grid over pairs; portfolio aggregates net day PnL."""
    modes = list(modes or ("fixed_lots", "spread_vol", "spread_vol_gate", "portfolio_mrc"))
    ids = [p for p in (focus_pairs or list(pair_bars.keys())) if p in pair_bars]
    grid: dict[str, Any] = {}
    for mode in modes:
        pair_results = {}
        # First pass without MRC scaling to collect returns for budget
        seed_rets: dict[str, list[float]] = {}
        for pid in ids:
            spec_a, spec_b = pair_specs[pid]
            seed = backtest_pair(
                pair_bars[pid],
                spec_a=spec_a,
                spec_b=spec_b,
                mode="spread_vol_gate" if mode == "portfolio_mrc" else mode,
                start=start,
                end=end,
                risk_budget_yuan=total_risk_budget / max(len(ids), 1),
                require_cointegration=require_cointegration,
                signal_mode=signal_mode,
            )
            pair_results[pid] = seed
            if seed.get("ok"):
                seed_rets[pid] = list((seed.get("day_pnl") or {}).values())

        budgets = allocate_mrc_budgets(ids, seed_rets, total_budget=total_risk_budget)
        if mode == "portfolio_mrc":
            # Re-run with MRC budgets
            pair_results = {}
            for pid in ids:
                spec_a, spec_b = pair_specs[pid]
                pair_results[pid] = backtest_pair(
                    pair_bars[pid],
                    spec_a=spec_a,
                    spec_b=spec_b,
                    mode="portfolio_mrc",
                    start=start,
                    end=end,
                    risk_budget_yuan=budgets.get(pid, total_risk_budget / max(len(ids), 1)),
                    require_cointegration=require_cointegration,
                    signal_mode=signal_mode,
                )

        # Portfolio curve
        all_days: set[str] = set()
        for r in pair_results.values():
            all_days |= set((r.get("day_pnl") or {}).keys())
        cal = sorted(d for d in all_days if (not start or d >= start) and (not end or d <= end))
        eq = capital
        curve = [eq]
        costs = 0.0
        gross = 0.0
        for d in cal:
            dp = 0.0
            for r in pair_results.values():
                dp += float((r.get("day_pnl") or {}).get(d, 0.0))
            gross += dp
            eq += dp
            curve.append(eq)
        for r in pair_results.values():
            costs += float(r.get("cost_yuan") or 0.0)
        net = gross - costs
        # Strip heavy day_pnl from pair payloads in summary
        slim = {
            pid: {k: v for k, v in r.items() if k != "day_pnl"}
            for pid, r in pair_results.items()
        }
        grid[mode] = {
            "portfolio": {
                "gross_pnl_yuan": round(gross, 2),
                "cost_yuan": round(costs, 2),
                "net_pnl_yuan": round(net, 2),
                "ret_pct": round(100.0 * net / capital, 3),
                "max_dd_pct": round(_max_dd_pct(curve), 3),
                "n_days": len(cal),
                "n_pairs": len(ids),
                "mrc_budgets": {k: round(v, 2) for k, v in budgets.items()} if mode == "portfolio_mrc" else None,
            },
            "pairs": slim,
        }

    return {
        "mode": "shadow_v1_2_research",
        "disclaimer": (
            "研究回测：费后近似、T+1成交（无开则用收）、含滑点与涨跌停跳过；"
            "非正式晋级/不下单/不写paper_book。"
        ),
        "window": {"start": start, "end": end},
        "capital_yuan": capital,
        "total_risk_budget_yuan": total_risk_budget,
        "require_cointegration": require_cointegration,
        "signal_mode": signal_mode,
        "focus_pairs": ids,
        "controls": grid,
    }


def load_pair_inputs_from_root(
    root,
    pairs: Sequence[tuple[str, str, str]],
):
    """Helper: load CODE0 bars + universe specs for (a,b,bucket) pairs."""
    from pathlib import Path

    from desk.loaders import load_universe
    from desk.local_bars import load_local_bars

    root = Path(root)
    uni = load_universe(root) or {}
    by_code = {
        str(s.get("code")).upper(): s
        for s in (uni.get("symbols") or [])
        if isinstance(s, dict) and s.get("code")
    }
    bars: dict[str, list[dict]] = {}
    specs: dict[str, tuple[dict, dict]] = {}
    meta = []
    for a, b, bucket in pairs:
        sa = contract_spec_from_universe_row(by_code.get(a))
        sb = contract_spec_from_universe_row(by_code.get(b))
        if not sa or not sb:
            meta.append({"pair": f"{a}/{b}", "ok": False, "reason": "missing_spec"})
            continue
        ba, _ = load_local_bars(root, a)
        bb, _ = load_local_bars(root, b)
        aligned = align_pair_bars(ba, bb)
        if not aligned.get("ok"):
            meta.append({"pair": f"{a}/{b}", "ok": False, "reason": "align_failed"})
            continue
        pid = f"{a}/{b}"
        bars[pid] = aligned["rows"]
        specs[pid] = (sa, sb)
        meta.append({
            "pair": pid, "bucket": bucket, "ok": True,
            "n": aligned["n"],
            "dropped_a_only": aligned["dropped_a_only"],
            "dropped_b_only": aligned["dropped_b_only"],
        })
    return bars, specs, meta
