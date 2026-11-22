# -*- coding: utf-8 -*-
"""One-shot shadow research BT for arb pairs — not paper_book / not formal V1.2."""
from __future__ import annotations

import json
import math
from pathlib import Path

from desk.arb_panel import CROSS_PAIRS
from desk.loaders import load_universe
from desk.local_bars import load_local_bars
from research.arbitrage_volatility import (
    evaluate_risk_gate,
    pair_correlation,
    rolling_spread,
    size_pair_position,
    spread_volatility,
)

ROOT = Path(".")
START, END = "2025-11-20", "2026-11-20"
CAPITAL = 1_000_000.0
RISK_BUDGET = 20_000.0
Z_ENTER, Z_EXIT = 1.5, 0.5
LOOKBACK = 60


def _closes(code: str) -> dict[str, float]:
    bars, _ = load_local_bars(ROOT, code)
    out: dict[str, float] = {}
    for b in bars:
        d = str(b.get("date") or "")[:10]
        try:
            c = float(b.get("close"))
        except (TypeError, ValueError):
            continue
        if len(d) == 10 and math.isfinite(c) and c > 0:
            out[d] = c
    return out


def _align(a: dict[str, float], b: dict[str, float]) -> list[dict]:
    days = sorted(set(a) & set(b))
    return [{"date": d, "leg_a_close": a[d], "leg_b_close": b[d]} for d in days]


def _max_dd(equity: list[float]) -> float:
    peak = equity[0]
    mdd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd * 100.0


def main() -> None:
    uni = load_universe(ROOT) or {}
    mult: dict[str, float] = {}
    for s in uni.get("symbols") or []:
        if isinstance(s, dict) and s.get("code"):
            m = float(s.get("mult") or s.get("multiplier") or 0)
            if m > 0:
                mult[str(s["code"]).upper()] = m

    results: list[dict] = []
    all_days: set[str] = set()
    pair_daily: dict[str, dict[str, float]] = {}

    for a, b, bucket in CROSS_PAIRS:
        ma, mb = mult.get(a), mult.get(b)
        if not ma or not mb:
            results.append({"pair": f"{a}/{b}", "ok": False, "reason": "missing_mult"})
            continue
        rows = _align(_closes(a), _closes(b))
        spreads = rolling_spread(rows, lookback=LOOKBACK, min_observations=30)
        by_date = {r["date"]: r for r in spreads}
        days = [r["date"] for r in spreads if START <= r["date"] <= END]
        if len(days) < 60:
            results.append(
                {"pair": f"{a}/{b}", "ok": False, "reason": "short_sample", "n": len(days)}
            )
            continue

        pos = 0
        qa = qb = 0
        cash_pnl = 0.0
        equity = [0.0]
        trades = 0
        blocked_entries = 0
        day_pnl: dict[str, float] = {}
        prev_a = prev_b = None

        for day in days:
            hist = [r for r in spreads if r["date"] <= day]
            vol = spread_volatility(hist)
            ok_hist = [r for r in hist if r.get("ok")]
            ca = [float(r["leg_a"]) for r in ok_hist]
            cb = [float(r["leg_b"]) for r in ok_hist]
            corr = pair_correlation(ca, cb, window=LOOKBACK)
            last = by_date[day]
            beta = last.get("hedge_ratio")
            gate = evaluate_risk_gate(volatility=vol, correlation=corr, hedge_ratio=beta)
            z = vol.get("spread_z")
            spread = last.get("spread") if last.get("ok") else None
            a_px = last.get("leg_a")
            b_px = last.get("leg_b")

            pnl = 0.0
            if pos != 0 and prev_a is not None and a_px is not None and b_px is not None:
                da = a_px - prev_a
                db = b_px - prev_b
                if pos > 0:
                    pnl = qa * da * ma + (-qb) * db * mb
                else:
                    pnl = (-qa) * da * ma + qb * db * mb
                cash_pnl += pnl
            day_pnl[day] = pnl
            equity.append(cash_pnl)

            if spread is None or z is None:
                prev_a, prev_b = a_px, b_px
                continue
            if pos != 0 and abs(z) <= Z_EXIT:
                pos = qa = qb = 0
            elif pos == 0 and abs(z) >= Z_ENTER:
                if not gate.get("allow_new_risk"):
                    blocked_entries += 1
                else:
                    sized = size_pair_position(
                        risk_budget_yuan=RISK_BUDGET,
                        spread_vol_points=vol.get("vol_ewma") or vol.get("vol_long"),
                        multiplier_a=ma,
                        multiplier_b=mb,
                        hedge_ratio=beta,
                        max_a_contracts=5,
                        gate=gate,
                    )
                    if sized.get("ok"):
                        qa = int(sized["contracts_a"])
                        qb = int(sized["contracts_b"])
                        pos = -1 if z >= Z_ENTER else 1
                        trades += 1
            prev_a, prev_b = a_px, b_px

        pair_daily[f"{a}/{b}"] = day_pnl
        all_days |= set(day_pnl)
        results.append(
            {
                "pair": f"{a}/{b}",
                "bucket": bucket,
                "ok": True,
                "start": days[0],
                "end": days[-1],
                "n_days": len(days),
                "pnl_yuan": round(cash_pnl, 2),
                "ret_on_1m_pct": round(100.0 * cash_pnl / CAPITAL, 3),
                "max_dd_on_pnl_path_pct": round(_max_dd(equity), 3),
                "trades": trades,
                "blocked_entries": blocked_entries,
                "final_pos": pos,
            }
        )

    cal = sorted(d for d in all_days if START <= d <= END)
    eq = 0.0
    curve = [CAPITAL]
    for d in cal:
        dp = sum(pair_daily[p].get(d, 0.0) for p in pair_daily)
        eq += dp
        curve.append(CAPITAL + eq)

    out = {
        "mode": "shadow_research_only",
        "disclaimer": (
            "非正式V1.2回测；无手续费/滑点/保证金/涨跌停；CODE0连续合约有换月噪声；"
            "信号为价差Z均值回归研究代理，非已验收策略；不可用于晋级/下单。"
        ),
        "window": {"start": START, "end": END},
        "capital_yuan": CAPITAL,
        "risk_budget_per_pair_yuan": RISK_BUDGET,
        "signal": {"z_enter": Z_ENTER, "z_exit": Z_EXIT, "fade_z": True},
        "portfolio": {
            "pnl_yuan": round(eq, 2),
            "ret_pct": round(100.0 * eq / CAPITAL, 3),
            "max_dd_pct": round(_max_dd(curve), 3),
            "n_pairs_ok": sum(1 for r in results if r.get("ok")),
            "n_days": len(cal),
        },
        "pairs": results,
    }
    hb_path = Path("historical_backtest_latest.json")
    if hb_path.exists():
        hb = json.loads(hb_path.read_text(encoding="utf-8"))
        out["path_a_reference"] = {
            "start": hb.get("start"),
            "end": hb.get("end"),
            "ret_pct": hb.get("ret_pct"),
            "max_dd_pct": hb.get("max_dd_pct"),
            "closed_trades": hb.get("closed_trades"),
            "mode": hb.get("mode"),
            "equity_start": hb.get("equity_start"),
            "equity_end": hb.get("equity_end"),
        }

    Path("lab/research").mkdir(parents=True, exist_ok=True)
    path = Path("lab/research/arb_shadow_bt_1y_latest.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "wrote": str(path),
                "portfolio": out["portfolio"],
                "path_a_reference": out.get("path_a_reference"),
                "pairs": [
                    {
                        k: r.get(k)
                        for k in (
                            "pair",
                            "pnl_yuan",
                            "ret_on_1m_pct",
                            "trades",
                            "blocked_entries",
                            "ok",
                            "reason",
                        )
                    }
                    for r in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
