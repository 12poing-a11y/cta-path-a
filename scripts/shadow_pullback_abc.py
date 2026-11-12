# -*- coding: utf-8 -*-
"""Shadow A/B/C trend-pullback with true 60m MA60 + 1R scale-out + trail.

A: MA trend pullback (structure stop)
B: same entry + ATR stop  (recommended baseline)
C: pullback + liquidity sweep + volume/OI confirm

HTF: 60-minute MA60 (price vs MA, MA slope). LTF entry: daily pullback ABC.
Exit: first 1R closes ~50% and stop→breakeven; remainder trails (ATR) or hits 2R.
Fill: next_open. Does not touch formal Path-A / paper_book.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import historical_backtest as hb  # noqa: E402
from minute_data import load_minute_bars_on_date, load_minute_bars_series  # noqa: E402
from path_a_filters import fill_cost  # noqa: E402
from position_rules import apply_portfolio_caps, compound_equity, risk_budget_yuan  # noqa: E402
from wyckoff_pullback import (  # noqa: E402
    apply_stop_target,
    apply_stop_target_intraday,
    atr14,
    detect_entry_abc,
    minute_bars_aligned_with_entry,
    ret_n,
    trend_ma60_60m,
)


def _scale_lots(lots: int) -> int:
    """Lots to close at 1R: half, at least 1 when lots>=2; 0 when lots==1 (BE+trail only)."""
    lots = int(lots or 0)
    if lots <= 1:
        return 0
    return max(1, lots // 2)


def _trail_stop(direction: str, entry: float, stop: float, bar: dict, atr: float, *, k: float = 1.0) -> float:
    """After 1R: trail remaining by ATR from close; never loosen past breakeven."""
    try:
        close = float(bar["close"])
    except (KeyError, TypeError, ValueError):
        return stop
    atr = float(atr or 0)
    if atr <= 0:
        return stop
    if direction == "多":
        be = float(entry)
        cand = close - k * atr
        return max(float(stop), be, cand)
    be = float(entry)
    cand = close + k * atr
    return min(float(stop), be, cand)


def _simulate_variant(
    series: dict,
    *,
    variant: str,
    equity0: float = 200_000.0,
    risk_pct: float = 1.0,
    reward_rr: float = 2.0,
    stop_atr_mult: float = 0.8,
    min_r20: float = 4.0,
    min_r60: float = 6.0,
    max_positions: int = 3,
    max_gross_pct: float = 50.0,
    max_port_risk: float = 8.0,
    max_per_bucket: int = 1,
    use_minute: bool = True,
    use_60m_trend: bool = True,
    trail_atr_mult: float = 1.0,
) -> dict:
    codes = sorted(series.keys())
    idx = {c: {b["date"]: i for i, b in enumerate(series[c]["hist"])} for c in codes}
    all_dates = sorted({b["date"] for c in codes for b in series[c]["hist"]})
    trade_dates = [
        d for d in all_dates if sum(1 for c in codes if d in idx[c]) >= max(1, len(codes) // 4)
    ]
    if len(trade_dates) > 80:
        trade_dates = trade_dates[60:]

    # Preload 60m series (cache only; no network).
    m60: dict[str, list] = {}
    htf_miss = 0
    if use_60m_trend:
        for code in codes:
            m60[code] = load_minute_bars_series(ROOT, code, "60")

    equity = float(equity0)
    peak = equity
    max_dd = 0.0
    pos: dict = {}
    closed: list[dict] = []
    exits = Counter()
    partial_n = 0
    trail_exits = 0
    htf_used = 0
    htf_blocked = 0

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
            mult = series[code]["meta"]["mult"]
            sign = 1 if p["direction"] == "多" else -1
            entry = float(p["entry"])
            risk_u = float(p["risk"])
            # Update trail for remainder after 1R scale.
            a = atr14(hist, i1) or float(p.get("atr") or 0)
            if p.get("scaled") and a > 0:
                p["stop"] = _trail_stop(
                    p["direction"], entry, float(p["stop"]), bar, a, k=trail_atr_mult
                )

            # Build effective targets: 1R always; 2R for remainder (or full if never scaled)
            t1 = entry + sign * risk_u
            t2 = entry + sign * reward_rr * risk_u
            reason, px = None, bar["close"]

            m_bars = []
            if use_minute:
                try:
                    m_bars = load_minute_bars_on_date(ROOT, code, d, period="15")
                except Exception:  # noqa: BLE001
                    m_bars = []
                if m_bars and str(p.get("entry_date") or "")[:10] == str(d)[:10]:
                    cutoff = f"{str(d)[:10]} 09:00:00"
                    m_bars = [
                        b
                        for b in m_bars
                        if str(b.get("datetime") or b.get("date") or "") >= cutoff
                    ]
                if m_bars and not minute_bars_aligned_with_entry(entry, m_bars):
                    m_bars = []

            def _touch(stop: float, target: float):
                if m_bars:
                    return apply_stop_target_intraday(
                        p["direction"], entry, stop, target, m_bars
                    )
                r, x = apply_stop_target(p["direction"], entry, stop, target, bar)
                return r, (float(x) if r else None)

            # Active target: 1R until scaled, else 2R. Stop always first inside helper.
            active_tp = t1 if not p.get("scaled") else t2
            r_hit, px_hit = _touch(float(p["stop"]), active_tp)
            if r_hit == "stop":
                reason, px = ("trail_stop" if p.get("scaled") else "stop"), px_hit
                if p.get("scaled"):
                    trail_exits += 1
            elif r_hit == "target" and px_hit is not None and not p.get("scaled"):
                # 1R: scale out / BE then optionally same-bar 2R on remainder
                sell = _scale_lots(int(p["lots"]))
                if sell <= 0:
                    p["scaled"] = True
                    p["stop"] = entry
                    partial_n += 1
                else:
                    day_cost += fill_cost(series[code]["meta"], px_hit, sell)
                    if prev_d is not None:
                        i0 = idx[code].get(prev_d)
                        if i0 is not None:
                            prev_close = p.get("mark_from") or hist[i0]["close"]
                            price_pnl += (px_hit - prev_close) * mult * sell * sign
                    closed.append(
                        {
                            "date": d,
                            "code": code,
                            "direction": p["direction"],
                            "lots": sell,
                            "entry_date": p["entry_date"],
                            "entry": entry,
                            "exit": px_hit,
                            "stop": p["stop"],
                            "target": t1,
                            "reason": "partial_1R",
                            "R": 1.0,
                            "variant": variant,
                        }
                    )
                    exits["partial_1R"] += 1
                    partial_n += 1
                    p["lots"] = int(p["lots"]) - sell
                    p["scaled"] = True
                    p["stop"] = entry
                    p["mark_from"] = px_hit
                    if p["lots"] <= 0:
                        del pos[code]
                        continue
                r2, px2 = _touch(float(p["stop"]), t2)
                if r2 == "stop":
                    reason, px = "trail_stop", px2
                    trail_exits += 1
                elif r2 == "target" and px2 is not None:
                    reason, px = "target", px2
            elif r_hit == "target" and px_hit is not None and p.get("scaled"):
                reason, px = "target", px_hit

            if reason is None and code in pos:
                r20, r60 = ret_n(hist, i1, 20), ret_n(hist, i1, 60)
                if r20 is not None and r60 is not None:
                    long_ok = r20 > 0 and r60 > 0
                    short_ok = r20 < 0 and r60 < 0
                    if p["direction"] == "多" and not long_ok:
                        reason, px = "signal", bar["close"]
                    elif p["direction"] == "空" and not short_ok:
                        reason, px = "signal", bar["close"]

            if code not in pos:
                continue
            if prev_d is not None and reason:
                i0 = idx[code].get(prev_d)
                if i0 is not None:
                    prev_close = p.pop("mark_from", None) or hist[i0]["close"]
                    price_pnl += (px - prev_close) * mult * p["lots"] * sign
            elif prev_d is not None and not reason:
                i0 = idx[code].get(prev_d)
                if i0 is not None:
                    prev_close = p.get("mark_from") or hist[i0]["close"]
                    price_pnl += (bar["close"] - prev_close) * mult * p["lots"] * sign
                    p["mark_from"] = bar["close"]

            if reason:
                day_cost += fill_cost(series[code]["meta"], px, p["lots"])
                r_mult = ((px - entry) * sign / risk_u) if risk_u > 0 else 0.0
                closed.append(
                    {
                        "date": d,
                        "code": code,
                        "direction": p["direction"],
                        "lots": p["lots"],
                        "entry_date": p["entry_date"],
                        "entry": entry,
                        "exit": px,
                        "stop": p["stop"],
                        "target": t2,
                        "reason": reason,
                        "R": round(r_mult, 3),
                        "variant": variant,
                        "scaled": bool(p.get("scaled")),
                    }
                )
                exits[reason] += 1
                del pos[code]

        equity += price_pnl - day_cost
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

        if len(pos) >= max_positions:
            continue
        cands = []
        for code in codes:
            if code in pos:
                continue
            hist = series[code]["hist"]
            i = idx[code].get(d)
            if i is None:
                continue
            htf_dir = None
            if use_60m_trend:
                bars = m60.get(code) or []
                if not bars:
                    htf_miss += 1
                    continue  # require real 60m when flag on
                htf = trend_ma60_60m(bars, asof=d)
                if htf is None:
                    htf_blocked += 1
                    continue
                htf_dir = htf["direction"]
                htf_used += 1
            plan = detect_entry_abc(
                hist,
                i,
                variant=variant,
                min_r20_pct=min_r20,
                min_r60_pct=min_r60,
                reward_rr=reward_rr,
                stop_atr_mult=stop_atr_mult,
                htf_direction=htf_dir,
            )
            if not plan:
                continue
            stop_dist = abs(float(plan["entry"]) - float(plan["stop"]))
            risk_per_lot = stop_dist * series[code]["meta"]["mult"]
            lots = int(math.floor(day_risk / risk_per_lot)) if risk_per_lot > 0 else 0
            if lots <= 0:
                continue
            cands.append(
                {
                    "code": code,
                    "direction": plan["direction"],
                    "lots": lots,
                    "close": plan["entry"],
                    "mult": series[code]["meta"]["mult"],
                    "r20": plan["r20"],
                    "r60": plan["r60"],
                    "atr": plan["atr"],
                    "bucket": series[code]["meta"].get("bucket"),
                    "entry": plan["entry"],
                    "stop": plan["stop"],
                    "target": plan["target"],
                    "reason": plan["reason"],
                    "risk": stop_dist,
                }
            )
        slots_left = max(0, max_positions - len(pos))
        selected, _ = apply_portfolio_caps(
            cands,
            equity=sizing_eq,
            max_positions=slots_left,
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
            bucket = str(c.get("bucket") or "_")
            if max_per_bucket > 0 and open_buckets.get(bucket, 0) >= max_per_bucket:
                continue
            filled = hb.next_open_fill(c, series[c["code"]]["hist"], idx[c["code"]][d])
            if filled is None:
                continue
            # keep risk distance after shift
            risk = abs(float(filled["entry"]) - float(filled["stop"]))
            day_cost_open = fill_cost(
                series[c["code"]]["meta"], filled["entry"], filled["lots"]
            )
            equity -= day_cost_open
            pos[c["code"]] = {
                "code": c["code"],
                "direction": filled["direction"],
                "lots": int(filled["lots"]),
                "entry": float(filled["entry"]),
                "entry_date": filled["entry_date"],
                "stop": float(filled["stop"]),
                "target": float(filled["target"]),
                "risk": risk,
                "atr": c.get("atr"),
                "bucket": c.get("bucket"),
                "mark_from": filled.get("mark_from"),
                "scaled": False,
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
            risk_u = float(p["risk"])
            r_mult = ((px - p["entry"]) * sign / risk_u) if risk_u > 0 else 0.0
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
                    "target": p["target"],
                    "reason": "eod",
                    "R": round(r_mult, 3),
                    "variant": variant,
                    "scaled": bool(p.get("scaled")),
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
    # entry count approximates unique entry_date+code (partials share entry)
    entries = len({(t.get("entry_date"), t.get("code")) for t in closed})
    return {
        "variant": variant,
        "start": trade_dates[0] if trade_dates else None,
        "end": trade_dates[-1] if trade_dates else None,
        "trade_days": len(trade_dates),
        "universe_n": len(codes),
        "universe": ",".join(codes),
        "equity_start": equity0,
        "equity_end": round(equity, 2),
        "ret_pct": round(ret_pct, 3),
        "max_dd_pct": round(max_dd, 3),
        "closed_legs": len(closed),
        "entries_approx": entries,
        "symbols_traded_n": len(codes_traded),
        "symbols_traded": codes_traded,
        "exits": dict(exits),
        "partial_1R_events": partial_n,
        "trail_stop_exits": trail_exits,
        "trade_win_rate": round(100.0 * len(wins) / len(closed), 2) if closed else None,
        "expectancy_r": round(avg_r, 3) if avg_r is not None else None,
        "max_lose_streak": max_lose_streak,
        "trades_by_code": dict(Counter(t["code"] for t in closed)),
        "htf_60m": {
            "enabled": use_60m_trend,
            "signals_used": htf_used,
            "flat_or_short_hist": htf_blocked,
            "missing_cache_skips": htf_miss,
        },
        "risk_pct": risk_pct,
        "reward_rr": reward_rr,
        "trail_atr_mult": trail_atr_mult,
        "fill_price": "next_open",
        "note": {
            "A": "60mMA60趋势+日线均线回调；结构止损；1R减仓+ATR跟踪",
            "B": "同上；初始止损=ATR×0.8；1R减仓+ATR跟踪",
            "C": "同上+扫荡+量仓；1R减仓+ATR跟踪",
        }[variant],
    }


def main() -> int:
    p = hb._load_cfg()
    all_syms = p["cfg"]["symbols"]
    print("[abc2] fetch full pack…")
    pack = hb._fetch_pack(all_syms)
    series_all, _err, _src = pack

    scopes = {
        "CF_SR": {c: series_all[c] for c in ("CF", "SR") if c in series_all},
        "full_universe": series_all,
    }
    rows = []
    for scope_name, series in scopes.items():
        print(f"[abc2] scope={scope_name} n={len(series)}")
        for variant in ("A", "B", "C"):
            print(f"  run {variant} (60m+1R+trail)…")
            one = _simulate_variant(series, variant=variant, use_60m_trend=True)
            one["scope"] = scope_name
            rows.append(one)
            print(
                f"    ret={one['ret_pct']}% dd={one['max_dd_pct']}% "
                f"legs={one['closed_legs']} entries~{one['entries_approx']} "
                f"wr={one['trade_win_rate']} syms={one['symbols_traded_n']} "
                f"exits={one['exits']} partial={one['partial_1R_events']}"
            )

    path_a = {"label": "path_a_mom_4_6_formal", "source": "historical_backtest_latest.json"}
    latest = ROOT / "historical_backtest_latest.json"
    if latest.exists():
        d = json.loads(latest.read_text(encoding="utf-8"))
        path_a.update(
            {
                "ret_pct": d.get("ret_pct"),
                "max_dd_pct": d.get("max_dd_pct"),
                "closed_trades": d.get("closed_trades"),
                "exits": d.get("exits"),
                "trade_win_rate": d.get("trade_win_rate"),
            }
        )

    payload = {
        "ok": True,
        "asof": str(date.today()),
        "label": "shadow_pullback_abc_60m_1r_trail",
        "framework": "ChatGPT: 60m MA60 trend + pullback; 1R scale-out + trail; B baseline",
        "share_ref": "https://chatgpt.com/s/t_6af4547ef9fc8191a045fd35cc26f045",
        "rules": {
            "htf": "60m SMA60; close>MA且MA上行做多；反之做空；走平不做",
            "entry": "日线回踩EMA20后收复，且与60m方向一致",
            "A_stop": "结构止损",
            "B_stop": "ATR×0.8",
            "C_extra": "扫前高/前低收回 + 量缩回补 + OI确认",
            "exit": "1R减半仓(≥2手)并止损移到成本；余仓ATR跟踪或2R清仓；1手仅移成本后跟踪",
            "fill": "next_open",
            "risk_pct": 1.0,
        },
        "rows": rows,
        "path_a_formal_ref": path_a,
    }
    out = ROOT / "archive" / f"shadow_pullback_abc_60m_1r_{date.today().strftime('%Y%m%d')}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[abc2] wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
