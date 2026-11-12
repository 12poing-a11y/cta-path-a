# -*- coding: utf-8 -*-
"""Shadow SuperTrend strategy (TradingView Pine port).

Defaults: ATR=10, Mult=3.0, hl2, Wilder ATR, flip long/short on signal.
Window: last 365 calendar days (approx trading window on available bars).
Fill: next_open. Portfolio caps mirror Path-A (Top3, bucket1, risk 1%).
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
from path_a_filters import fill_cost  # noqa: E402
from position_rules import apply_portfolio_caps, compound_equity, risk_budget_yuan  # noqa: E402
from supertrend import supertrend_series  # noqa: E402


def _parse_day(s: str) -> datetime:
    return datetime.strptime(str(s)[:10], "%Y-%m-%d")


def _simulate_supertrend(
    series: dict,
    *,
    equity0: float = 200_000.0,
    risk_pct: float = 1.0,
    atr_period: int = 10,
    multiplier: float = 3.0,
    max_positions: int = 3,
    max_gross_pct: float = 50.0,
    max_port_risk: float = 8.0,
    max_per_bucket: int = 1,
    last_days: int = 365,
    stop_on_band: bool = True,
) -> dict:
    codes = sorted(series.keys())
    st_map = {
        c: supertrend_series(
            series[c]["hist"], atr_period=atr_period, multiplier=multiplier, use_wilder_atr=True
        )
        for c in codes
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
    trade_log: list[dict] = []
    equity_curve: list[dict] = []
    exits = Counter()
    signals = Counter()
    if trade_dates:
        equity_curve.append({"date": trade_dates[0], "equity": round(equity0, 2)})

    for di, d in enumerate(trade_dates):
        price_pnl = 0.0
        day_cost = 0.0
        prev_d = trade_dates[di - 1] if di > 0 else None
        sizing_eq = compound_equity(equity, equity0, True)
        day_risk = risk_budget_yuan(sizing_eq, risk_pct, 1.0)

        # manage exits: opposite flip already handled via reverse entry;
        # optional: stop if close beyond SuperTrend band
        for code, p in list(pos.items()):
            hist = series[code]["hist"]
            i1 = idx[code].get(d)
            if i1 is None:
                continue
            bar = hist[i1]
            st = (st_map[code][i1] or {}) if i1 < len(st_map[code]) else {}
            mult = series[code]["meta"]["mult"]
            sign = 1 if p["direction"] == "多" else -1
            reason = None
            px = bar["close"]
            # flip signals close & reverse later in entries
            if p["direction"] == "多" and st.get("sell"):
                reason, px = "flip", float(st.get("dn") or bar["close"])
            elif p["direction"] == "空" and st.get("buy"):
                reason, px = "flip", float(st.get("up") or bar["close"])
            elif stop_on_band and st:
                band = float(st.get("band") or 0)
                if p["direction"] == "多" and float(bar["close"]) < band:
                    reason, px = "band", band
                elif p["direction"] == "空" and float(bar["close"]) > band:
                    reason, px = "band", band

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
                trade_log.append(
                    {
                        "date": d,
                        "code": code,
                        "action": "close",
                        "direction": "long" if p["direction"] == "多" else "short",
                        "price": px,
                        "entry_date": p["entry_date"],
                        "pnl_pct": round(r_mult * risk / max(p["entry"], 1e-9) * 100, 3)
                        if risk > 0
                        else None,
                        "reason": reason,
                    }
                )
                exits[reason] += 1
                del pos[code]

        equity += price_pnl - day_cost
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

        # new / reverse entries from today's close signal → next_open
        cands = []
        for code in codes:
            hist = series[code]["hist"]
            i = idx[code].get(d)
            if i is None:
                continue
            st = st_map[code][i] if i < len(st_map[code]) else None
            if not st:
                continue
            direction = None
            if st.get("buy"):
                direction = "多"
                signals["buy"] += 1
            elif st.get("sell"):
                direction = "空"
                signals["sell"] += 1
            else:
                continue
            # if already same side, skip
            if code in pos and pos[code]["direction"] == direction:
                continue
            close = float(hist[i]["close"])
            atr = float(st["atr"])
            band = float(st["band"])
            # risk to band (SuperTrend structural stop)
            stop = band
            stop_dist = abs(close - stop)
            if stop_dist <= 0:
                stop_dist = max(atr * multiplier * 0.5, close * 0.005)
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
                    "r20": abs(close - band) / close * 100,
                    "r60": abs(close - band) / close * 100,
                    "atr": atr,
                    "bucket": series[code]["meta"].get("bucket"),
                    "entry": close,
                    "stop": stop,
                    "target": close,  # unused; flip exit
                    "reason": "supertrend_buy" if direction == "多" else "supertrend_sell",
                }
            )

        # free slots: allow reverse by closing already done above
        slots_left = max(0, max_positions - len(pos))
        selected, _ = apply_portfolio_caps(
            cands,
            equity=sizing_eq,
            max_positions=max(slots_left, len(cands)),  # rank then clip below
            max_gross_exposure_pct=max_gross_pct,
            max_portfolio_risk_pct=max_port_risk,
            max_per_bucket=max_per_bucket,
            min_r20_pct=0.0,
            min_r60_pct=0.0,
        )
        open_buckets = Counter(str(p.get("bucket") or "_") for p in pos.values())
        for c in selected:
            if len(pos) >= max_positions and c["code"] not in pos:
                break
            if c["code"] in pos:
                continue
            bucket = str(c.get("bucket") or "_")
            if max_per_bucket > 0 and open_buckets.get(bucket, 0) >= max_per_bucket:
                continue
            filled = hb.next_open_fill(c, series[c["code"]]["hist"], idx[c["code"]][d])
            if filled is None:
                continue
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
                "atr": float(c.get("atr") or 0) or None,
                "bucket": c.get("bucket"),
                "mark_from": filled.get("mark_from"),
            }
            trade_log.append(
                {
                    "date": filled["entry_date"],
                    "code": c["code"],
                    "action": "open",
                    "direction": "long" if filled["direction"] == "多" else "short",
                    "price": float(filled["entry"]),
                    "entry_date": filled["entry_date"],
                    "pnl_pct": None,
                    "reason": None,
                    "stop": float(filled["stop"]),
                    "target": None,
                }
            )
            open_buckets[bucket] = open_buckets.get(bucket, 0) + 1

        if di > 0 or price_pnl or day_cost:
            equity_curve.append({"date": d, "equity": round(equity, 2)})

    # Open book for desk proxy positions (do not force EOD flatten).
    asof = trade_dates[-1] if trade_dates else None
    final_positions: list[dict] = []
    if asof and equity > 0:
        for code, p in pos.items():
            hist = series[code]["hist"]
            i1 = idx[code].get(asof)
            if i1 is None:
                continue
            last_px = float(hist[i1]["close"])
            meta = series[code].get("meta") or {}
            mult = float(meta.get("mult") or 0) or None
            direction = "long" if p["direction"] == "多" else "short"
            notional = abs(float(p["lots"])) * last_px * mult if mult else None
            weight = (notional / equity) if (notional and equity) else None
            if direction == "short" and weight is not None:
                weight = -abs(weight)
            sign = 1 if direction == "long" else -1
            unreal = None
            if p.get("entry"):
                unreal = round((last_px / float(p["entry"]) - 1.0) * sign * 100.0, 3)
            final_positions.append(
                {
                    "code": code,
                    "name": meta.get("name"),
                    "direction": direction,
                    "weight": round(weight, 6) if weight is not None else None,
                    "notional_yuan": round(notional, 2) if notional is not None else None,
                    "lots_equiv": float(p["lots"]),
                    "entry_date": p.get("entry_date"),
                    "entry_price": p.get("entry"),
                    "last_price": last_px,
                    "unrealized_pct": unreal,
                    "score_z": None,
                    "stop": round(float(p["stop"]), 4) if p.get("stop") is not None else None,
                    "target": None,
                    "atr": round(float(p["atr"]), 4) if p.get("atr") is not None else None,
                }
            )
        final_positions.sort(key=lambda r: (r["direction"] != "long", -abs(r.get("weight") or 0)))

    wins = [t for t in closed if float(t.get("R") or 0) > 0]
    max_lose_streak = 0
    streak = 0
    for t in closed:
        if float(t.get("R") or 0) <= 0:
            streak += 1
            max_lose_streak = max(max_lose_streak, streak)
        else:
            streak = 0
    codes_traded = sorted({t["code"] for t in closed} | {p["code"] for p in final_positions})
    ret_pct = (equity / equity0 - 1) * 100
    avg_r = sum(float(t["R"]) for t in closed) / len(closed) if closed else None
    if len(equity_curve) < 2 and trade_dates:
        equity_curve = [
            {"date": trade_dates[0], "equity": round(equity0, 2)},
            {"date": trade_dates[-1], "equity": round(equity, 2)},
        ]
    return {
        "ok": True,
        "strategy": "supertrend_flip",
        "atr_period": atr_period,
        "multiplier": multiplier,
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
        "stop_on_band": stop_on_band,
        "equity_curve": equity_curve,
        "positions_asof": asof,
        "final_positions": final_positions,
        "trade_log": trade_log[-80:],
    }


PROXY_ID = "proxy_supertrend"
POSITIONS_DISCLAIMER = (
    "研究模拟持仓 · 非实盘 · SuperTrend 观察袖套，与 Path-A paper_book 分离。"
    "ATR10×3 Wilder 翻转；T+1 next_open；样本对照用，不构成交易建议。"
)


def _to_proxy_payload(one: dict) -> dict:
    """Desk/proxy_cta-compatible artifact for overview + 模拟仓对照."""
    curve = one.get("equity_curve") or []
    eq0 = float(one.get("equity_start") or 200_000.0)
    eq1 = float(one.get("equity_end") or eq0)
    ret = float(one.get("ret_pct") or 0.0)
    dd = float(one.get("max_dd_pct") or 0.0)
    return {
        "ok": True,
        "strategy": PROXY_ID,
        "proxy_of": "supertrend_flip",
        "family": "supertrend_observe",
        "name": "本地代理·SuperTrend观察",
        "description": (
            "TradingView SuperTrend（ATR10×3，Wilder）翻转观察袖套："
            "Path-A 样本偏少时用于影子对照；不改正式 seats 开仓。"
        ),
        "track_source": "scripts/shadow_supertrend.py (observe sleeve)",
        "start": one.get("start"),
        "end": one.get("end"),
        "equity_start": eq0,
        "equity_end": eq1,
        "ret_pct": round(ret, 3),
        "ret_ann_pct": round(ret, 3),
        "max_dd_pct": round(dd, 3),
        "sharpe": None,
        "calmar": round((ret / dd), 3) if dd > 0 else None,
        "stop_atr_mult": one.get("multiplier"),
        "reward_rr": None,
        "atr_period": one.get("atr_period"),
        "exit_counts": one.get("exits") or {},
        "equity_curve": curve,
        "positions_asof": one.get("positions_asof"),
        "positions_kind": "research_simulated_not_live",
        "positions_disclaimer": POSITIONS_DISCLAIMER,
        "final_positions": one.get("final_positions") or [],
        "trade_log": one.get("trade_log") or [],
        "summary": (
            f"proxy {PROXY_ID} ret={ret:.2f}% dd={dd:.2f}% "
            f"closed={one.get('closed_trades')} held={len(one.get('final_positions') or [])}"
        ),
        "observe_only": True,
        "paper_only": True,
    }


def write_proxy_supertrend(root: Path, series: dict | None = None) -> dict:
    """Refresh SuperTrend shadow archive + desk proxy JSON (soft for daily_update)."""
    root = Path(root)
    if series is None:
        p = hb._load_cfg()
        series, _e, _s = hb._fetch_pack(p["cfg"]["symbols"])
    one = _simulate_supertrend(series, stop_on_band=True)
    one["scope"] = "full_universe"
    one["mode"] = "band_stop"
    path_a = {}
    latest = root / "historical_backtest_latest.json"
    if latest.exists():
        try:
            d = json.loads(latest.read_text(encoding="utf-8"))
            path_a = {
                "ret_pct": d.get("ret_pct"),
                "max_dd_pct": d.get("max_dd_pct"),
                "closed_trades": d.get("closed_trades"),
                "label": "path_a_formal",
                "min_r20_pct": d.get("min_r20_pct"),
                "min_r60_pct": d.get("min_r60_pct"),
                "stop_atr_mult": d.get("stop_atr_mult"),
                "reward_rr": d.get("reward_rr"),
            }
        except (OSError, json.JSONDecodeError):
            path_a = {}
    shadow = {
        "ok": True,
        "asof": str(date.today()),
        "label": "shadow_supertrend",
        "pine": {
            "atr_period": 10,
            "multiplier": 3.0,
            "src": "hl2",
            "atr_method": "wilder/RMA (changeATR=true)",
            "entry": "buySignal / sellSignal flip",
            "window": "last 365 calendar days",
        },
        "rows": [one],
        "path_a_formal_ref": path_a,
        "readout": (
            "SuperTrend observe sleeve beside Path-A. "
            "Does not replace mom_4_6 formal until it beats ret/DD with enough trades."
        ),
    }
    arch = root / "archive" / f"shadow_supertrend_{date.today().strftime('%Y%m%d')}.json"
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_text(json.dumps(shadow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    proxy = _to_proxy_payload(one)
    out_dir = root / "external" / "strategies"
    extra_dir = root / "desk" / "strategies" / "extra"
    out_dir.mkdir(parents=True, exist_ok=True)
    extra_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = out_dir / f"{PROXY_ID}.json"
    proxy_path.write_text(json.dumps(proxy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extra = {
        "id": PROXY_ID,
        "name": "本地代理·SuperTrend观察",
        "description": proxy["description"],
        "curve_file": f"external/strategies/{PROXY_ID}.json",
        "tags": ["proxy", "supertrend", "observe", "shadow"],
    }
    (extra_dir / f"{PROXY_ID}.json").write_text(
        json.dumps(extra, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "ok": bool(one.get("ok")),
        "ret_pct": one.get("ret_pct"),
        "max_dd_pct": one.get("max_dd_pct"),
        "held_n": len(one.get("final_positions") or []),
        "asof": one.get("positions_asof"),
        "archive": str(arch.relative_to(root)),
        "proxy": str(proxy_path.relative_to(root)),
    }


def main() -> int:
    # unit smoke: synthetic up then down
    hist = []
    px = 100.0
    for i in range(80):
        px += 0.5
        hist.append({"date": f"2026-01-{(i%28)+1:02d}", "open": px, "high": px + 1, "low": px - 1, "close": px})
    for i in range(40):
        px -= 1.0
        hist.append({"date": f"2026-03-{(i%28)+1:02d}", "open": px, "high": px + 1, "low": px - 1, "close": px})
    st = supertrend_series(hist)
    flips = sum(1 for x in st if x and (x["buy"] or x["sell"]))
    print(f"[st] synthetic flips={flips}")

    p = hb._load_cfg()
    print("[st] fetch pack…")
    pack = hb._fetch_pack(p["cfg"]["symbols"])
    series_all, _e, _s = pack

    scopes = {
        "CF_SR": {c: series_all[c] for c in ("CF", "SR") if c in series_all},
        "full_universe": series_all,
    }
    rows = []
    for name, series in scopes.items():
        print(f"[st] scope={name}")
        for stop_band in (True, False):
            tag = "band_stop" if stop_band else "flip_only"
            print(f"  run {tag}…")
            one = _simulate_supertrend(series, stop_on_band=stop_band)
            one["scope"] = name
            one["mode"] = tag
            rows.append(one)
            print(
                f"    ret={one['ret_pct']}% dd={one['max_dd_pct']}% n={one['closed_trades']} "
                f"wr={one['trade_win_rate']} held={len(one.get('final_positions') or [])} "
                f"exits={one['exits']}"
            )

    # Desk proxy + archive from full-universe band_stop
    print("[st] write proxy + archive…")
    meta = write_proxy_supertrend(ROOT, series=series_all)
    print("[st] wrote", meta)
    return 0 if meta.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
