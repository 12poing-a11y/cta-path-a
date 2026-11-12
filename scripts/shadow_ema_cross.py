# -*- coding: utf-8 -*-
"""Shadow EMA10/20 crossover flip (TradingView port).

Pine: crossover → long, crossunder → short (always-in flip).
Fill: next_open. Window: last 365 calendar days.
Risk stop for sizing only: 1.5×ATR14 (exit is opposite cross).
Does not modify formal Path-A.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import historical_backtest as hb  # noqa: E402
from ema_cross import ema_cross_series  # noqa: E402
from path_a_filters import fill_cost  # noqa: E402
from position_rules import apply_portfolio_caps, compound_equity, risk_budget_yuan  # noqa: E402
from wyckoff_pullback import atr14  # noqa: E402


def _parse_day(s: str) -> datetime:
    return datetime.strptime(str(s)[:10], "%Y-%m-%d")


def _simulate(
    series: dict,
    *,
    equity0: float = 200_000.0,
    risk_pct: float = 1.0,
    fast: int = 10,
    slow: int = 20,
    stop_atr_mult: float = 1.5,
    max_positions: int = 3,
    max_gross_pct: float = 50.0,
    max_port_risk: float = 8.0,
    max_per_bucket: int = 1,
    last_days: int = 365,
) -> dict:
    codes = sorted(series.keys())
    sig_map = {
        c: ema_cross_series(series[c]["hist"], fast=fast, slow=slow) for c in codes
    }
    idx = {c: {b["date"]: i for i, b in enumerate(series[c]["hist"])} for c in codes}
    all_dates = sorted({b["date"] for c in codes for b in series[c]["hist"]})
    if not all_dates:
        return {"ok": False, "error": "no dates"}
    end = _parse_day(all_dates[-1])
    start_cut = end - timedelta(days=last_days)
    trade_dates = [d for d in all_dates if _parse_day(d) >= start_cut]

    equity = float(equity0)
    peak = equity
    max_dd = 0.0
    pos: dict = {}
    closed: list[dict] = []
    exits = Counter()
    signals = Counter()

    for di, d in enumerate(trade_dates):
        price_pnl = 0.0
        day_cost = 0.0
        prev_d = trade_dates[di - 1] if di > 0 else None
        sizing_eq = compound_equity(equity, equity0, True)
        day_risk = risk_budget_yuan(sizing_eq, risk_pct, 1.0)

        for code, p in list(pos.items()):
            hist = series[code]["hist"]
            i1 = idx[code].get(d)
            if i1 is None:
                continue
            bar = hist[i1]
            sig = sig_map[code][i1] if i1 < len(sig_map[code]) else None
            mult = series[code]["meta"]["mult"]
            sign = 1 if p["direction"] == "多" else -1
            reason = None
            px = bar["close"]
            if sig:
                if p["direction"] == "多" and sig.get("short"):
                    reason, px = "flip", bar["close"]
                elif p["direction"] == "空" and sig.get("long"):
                    reason, px = "flip", bar["close"]
            if prev_d is not None:
                i0 = idx[code].get(prev_d)
                if i0 is not None:
                    prev_close = p.pop("mark_from", None) or hist[i0]["close"]
                    exit_px = px if reason else bar["close"]
                    price_pnl += (exit_px - prev_close) * mult * p["lots"] * sign
                    if not reason:
                        p["mark_from"] = bar["close"]
            if reason:
                day_cost += fill_cost(series[code]["meta"], px, p["lots"])
                risk = abs(float(p["entry"]) - float(p["stop"]))
                r_mult = ((px - p["entry"]) * sign / risk) if risk > 0 else 0.0
                closed.append(
                    {
                        "date": d,
                        "code": code,
                        "direction": p["direction"],
                        "lots": p["lots"],
                        "entry_date": p["entry_date"],
                        "entry": p["entry"],
                        "exit": px,
                        "stop": p["stop"],
                        "reason": reason,
                        "R": round(r_mult, 3),
                    }
                )
                exits[reason] += 1
                del pos[code]

        equity += price_pnl - day_cost
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

        cands = []
        for code in codes:
            hist = series[code]["hist"]
            i = idx[code].get(d)
            if i is None:
                continue
            sig = sig_map[code][i] if i < len(sig_map[code]) else None
            if not sig:
                continue
            direction = None
            if sig.get("long"):
                direction = "多"
                signals["long"] += 1
            elif sig.get("short"):
                direction = "空"
                signals["short"] += 1
            else:
                continue
            if code in pos and pos[code]["direction"] == direction:
                continue
            close = float(hist[i]["close"])
            a = atr14(hist, i)
            if a is None or a <= 0:
                continue
            stop_dist = stop_atr_mult * a
            stop = close - stop_dist if direction == "多" else close + stop_dist
            risk_per_lot = stop_dist * series[code]["meta"]["mult"]
            lots = int(math.floor(day_risk / risk_per_lot)) if risk_per_lot > 0 else 0
            if lots <= 0:
                continue
            cands.append(
                {
                    "code": code,
                    "direction": direction,
                    "lots": lots,
                    "close": close,
                    "mult": series[code]["meta"]["mult"],
                    "r20": 1.0,
                    "r60": 1.0,
                    "atr": a,
                    "bucket": series[code]["meta"].get("bucket"),
                    "entry": close,
                    "stop": stop,
                    "target": close,
                    "reason": "ema_cross_long" if direction == "多" else "ema_cross_short",
                }
            )

        selected, _ = apply_portfolio_caps(
            cands,
            equity=sizing_eq,
            max_positions=max(1, max_positions),
            max_gross_exposure_pct=max_gross_pct,
            max_portfolio_risk_pct=max_port_risk,
            max_per_bucket=max_per_bucket,
            min_r20_pct=0.0,
            min_r60_pct=0.0,
        )
        open_buckets = Counter(str(p.get("bucket") or "_") for p in pos.values())
        for c in selected:
            if len(pos) >= max_positions:
                break
            if c["code"] in pos:
                continue
            bucket = str(c.get("bucket") or "_")
            if max_per_bucket > 0 and open_buckets.get(bucket, 0) >= max_per_bucket:
                continue
            filled = hb.next_open_fill(c, series[c["code"]]["hist"], idx[c["code"]][d])
            if filled is None:
                continue
            equity -= fill_cost(series[c["code"]]["meta"], filled["entry"], filled["lots"])
            pos[c["code"]] = {
                "code": c["code"],
                "direction": filled["direction"],
                "lots": int(filled["lots"]),
                "entry": float(filled["entry"]),
                "entry_date": filled["entry_date"],
                "stop": float(filled["stop"]),
                "bucket": c.get("bucket"),
                "mark_from": filled.get("mark_from"),
            }
            open_buckets[bucket] = open_buckets.get(bucket, 0) + 1

    if trade_dates:
        d = trade_dates[-1]
        for code, p in list(pos.items()):
            hist = series[code]["hist"]
            i1 = idx[code].get(d)
            if i1 is None:
                continue
            px = hist[i1]["close"]
            sign = 1 if p["direction"] == "多" else -1
            risk = abs(float(p["entry"]) - float(p["stop"]))
            r_mult = ((px - p["entry"]) * sign / risk) if risk > 0 else 0.0
            closed.append(
                {
                    "date": d,
                    "code": code,
                    "direction": p["direction"],
                    "lots": p["lots"],
                    "entry_date": p["entry_date"],
                    "entry": p["entry"],
                    "exit": px,
                    "stop": p["stop"],
                    "reason": "eod",
                    "R": round(r_mult, 3),
                }
            )
            exits["eod"] += 1

    wins = [t for t in closed if float(t.get("R") or 0) > 0]
    max_lose_streak = 0
    streak = 0
    for t in closed:
        if float(t.get("R") or 0) <= 0:
            streak += 1
            max_lose_streak = max(max_lose_streak, streak)
        else:
            streak = 0
    codes_traded = sorted({t["code"] for t in closed})
    ret_pct = (equity / equity0 - 1) * 100
    avg_r = sum(float(t["R"]) for t in closed) / len(closed) if closed else None
    return {
        "ok": True,
        "strategy": "ema_cross_flip",
        "fast": fast,
        "slow": slow,
        "fill_price": "next_open",
        "window_days": last_days,
        "start": trade_dates[0] if trade_dates else None,
        "end": trade_dates[-1] if trade_dates else None,
        "trade_days": len(trade_dates),
        "universe_n": len(codes),
        "equity_start": equity0,
        "equity_end": round(equity, 2),
        "ret_pct": round(ret_pct, 3),
        "max_dd_pct": round(max_dd, 3),
        "closed_trades": len(closed),
        "symbols_traded_n": len(codes_traded),
        "symbols_traded": codes_traded,
        "exits": dict(exits),
        "signals": dict(signals),
        "trade_win_rate": round(100.0 * len(wins) / len(closed), 2) if closed else None,
        "expectancy_r": round(avg_r, 3) if avg_r is not None else None,
        "max_lose_streak": max_lose_streak,
        "trades_by_code": dict(Counter(t["code"] for t in closed)),
        "risk_pct": risk_pct,
        "stop_atr_mult_sizing": stop_atr_mult,
        "note": "Pine 无硬止损；此处 1.5×ATR 仅用于手数，出场=反向交叉",
    }


def main() -> int:
    # smoke
    hist = [{"close": 100 + i * 0.5, "high": 101, "low": 99, "open": 100} for i in range(40)]
    for i in range(20):
        hist.append({"close": 120 - i, "high": 121, "low": 118, "open": 120})
    sig = ema_cross_series(hist)
    assert any(x and x["short"] for x in sig)
    print("[ema] smoke ok")

    p = hb._load_cfg()
    print("[ema] fetch pack…")
    pack = hb._fetch_pack(p["cfg"]["symbols"])
    series_all, _e, _s = pack
    scopes = {
        "CF_SR": {c: series_all[c] for c in ("CF", "SR") if c in series_all},
        "full_universe": series_all,
    }
    rows = []
    for name, series in scopes.items():
        print(f"[ema] scope={name}")
        one = _simulate(series)
        one["scope"] = name
        rows.append(one)
        print(
            f"  ret={one['ret_pct']}% dd={one['max_dd_pct']}% n={one['closed_trades']} "
            f"wr={one['trade_win_rate']} syms={one['symbols_traded_n']} exits={one['exits']}"
        )

    refs = {}
    for path, key in (
        (ROOT / "historical_backtest_latest.json", "path_a_mom_4_6"),
        (ROOT / "archive" / "shadow_supertrend_20261111.json", "supertrend"),
    ):
        if not path.exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        if key == "supertrend":
            row = next(
                (
                    r
                    for r in d.get("rows") or []
                    if r.get("scope") == "full_universe" and r.get("mode") == "band_stop"
                ),
                None,
            )
            if row:
                refs[key] = {
                    "ret_pct": row.get("ret_pct"),
                    "max_dd_pct": row.get("max_dd_pct"),
                    "closed_trades": row.get("closed_trades"),
                    "trade_win_rate": row.get("trade_win_rate"),
                }
        else:
            refs[key] = {
                "ret_pct": d.get("ret_pct"),
                "max_dd_pct": d.get("max_dd_pct"),
                "closed_trades": d.get("closed_trades"),
                "trade_win_rate": d.get("trade_win_rate"),
            }

    payload = {
        "ok": True,
        "asof": str(date.today()),
        "label": "shadow_ema_cross",
        "pine": {
            "fast": 10,
            "slow": 20,
            "entry": "crossover(ema10,ema20)=long; crossunder=short",
            "window": "last 365 calendar days (data-limited)",
        },
        "rows": rows,
        "refs": refs,
        "readout": (
            "EMA10/20 flip is a fast always-in sleeve; expect more trades and whipsaw "
            "vs SuperTrend. Compare fee-adjusted ret/DD/win-rate under next_open caps."
        ),
    }
    out = ROOT / "archive" / f"shadow_ema_cross_{date.today().strftime('%Y%m%d')}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[ema] wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
