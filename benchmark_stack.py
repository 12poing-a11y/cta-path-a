# -*- coding: utf-8 -*-
"""Paper benchmark: slow trend + capped 20/60 + carry, versus Path-A base.

Rules are frozen. This does not change universe.json or the daily signal.
Prices are the main continuous contract. Sina and Tencent come first;
iFinD is used only when that set is short or stale, and for a carry curve
when Sina returns fewer than two delivery months.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from historical_backtest import (  # noqa: E402
    _fetch_ifind_history,
    _load_cfg,
    atr14,
    ret_n,
    simulate,
)
from ifind_call import reset_usage, usage_report  # noqa: E402
from market_data import load_free_bars, merge_bars, series_sufficient  # noqa: E402
from path_a_filters import fill_cost  # noqa: E402
from position_rules import compound_equity, risk_budget_yuan  # noqa: E402
from public_curve import curve_coverage, load_curves  # noqa: E402

SLOW = (120, 250)
FAST = (20, 60)
FAST_RISK_SHARE = 1.0 / 3.0
CARRY_MIN = 0.005
WARMUP = 250


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def load_main(u: dict) -> tuple[list[dict], dict]:
    """Main continuous bars through yesterday. iFinD only fills a short free set."""
    code = u["code"]
    free, meta = load_free_bars(code)
    need = max(80, WARMUP + 20)
    if series_sufficient(free, need):
        bars = list(free)
        meta["ifind"] = False
    else:
        ifind = _fetch_ifind_history(u, WARMUP)
        bars = merge_bars(free, ifind)
        meta["ifind_n"] = len(ifind)
        meta["ifind"] = True
        meta["source"] = (meta.get("source") + "+ifind") if meta.get("source") else "ifind"
    yday = _yesterday()
    bars = [b for b in bars if str(b.get("date") or "") <= yday]
    meta["bars"] = len(bars)
    meta["contract"] = "主力连续"
    print(
        f"  source={meta.get('source')} sina={meta.get('sina_n')} "
        f"tencent={meta.get('tencent_n')} ifind={meta.get('ifind')} "
        f"bars={len(bars)} last={bars[-1]['date'] if bars else '-'}"
    )
    return bars, meta


def _same_sign(a: float | None, b: float | None) -> int:
    if a is None or b is None or a == 0 or b == 0:
        return 0
    if a > 0 and b > 0:
        return 1
    if a < 0 and b < 0:
        return -1
    return 0


def _lots(risk_yuan: float, atr: float, mult: float) -> int:
    per = atr * mult
    if per <= 0 or risk_yuan <= 0:
        return 0
    return int(math.floor(risk_yuan / per))


def _carry_dir(pair) -> tuple[int, float | None]:
    if not pair:
        return 0, None
    front, nxt = pair
    if front is None or nxt is None or nxt == 0:
        return 0, None
    gap = front / nxt - 1.0
    if abs(gap) < CARRY_MIN:
        return 0, gap
    return (1 if gap > 0 else -1), gap


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _window_stats(day_pnls: list[dict], equity0: float, start: str, end: str) -> dict:
    rows = [r for r in day_pnls if start <= r["date"] <= end]
    equity = equity0
    peak = equity
    max_dd = 0.0
    for row in rows:
        equity += row["pnl"]
        peak = max(peak, equity)
        if peak:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    ret = (equity / equity0 - 1) * 100 if equity0 else 0.0
    return {
        "start": rows[0]["date"] if rows else start,
        "end": rows[-1]["date"] if rows else end,
        "trade_days": len(rows),
        "equity_end": round(equity, 2),
        "ret_pct": round(ret, 3),
        "max_dd_pct": round(max_dd, 3),
        "pnl_by_sleeve": {
            name: round(sum(r["sleeve_pnl"].get(name, 0.0) for r in rows), 2)
            for name in ("slow", "fast", "carry")
        },
        "days_with_sleeve": {
            name: sum(1 for r in rows if r["sleeve_lots"].get(name))
            for name in ("slow", "fast", "carry")
        },
        "cost_yuan": round(sum(r["cost"] for r in rows), 2),
    }


def _equity_curve_from_day_pnls(day_pnls: list[dict], equity0: float) -> list[dict]:
    """Accumulate day_pnls into a Path-A-shaped equity_curve for the desk."""
    equity = float(equity0)
    peak = equity
    curve: list[dict] = []
    for row in day_pnls:
        pnl = float(row.get("pnl") or 0.0)
        equity += pnl
        peak = max(peak, equity)
        dd = ((peak - equity) / peak * 100) if peak else 0.0
        sleeve = row.get("sleeve_pnl") or {}
        curve.append(
            {
                "date": row["date"],
                "equity": round(equity, 2),
                "pnl": round(pnl, 2),
                "dd_pct": round(dd, 3),
                "held": int(row.get("held") or 0),
                "sleeve_pnl": {
                    name: round(float(sleeve.get(name) or 0.0), 2)
                    for name in ("slow", "fast", "carry")
                },
            }
        )
    return curve


def _downsample_weekly(curve: list[dict]) -> list[dict]:
    if not curve:
        return []
    out: list[dict] = []
    last_week = None
    for row in curve:
        y, _m, d = row["date"].split("-")
        week = f"{y}-W{int(d) // 7}"
        if week != last_week:
            out.append(row)
            last_week = week
    if curve and (not out or out[-1]["date"] != curve[-1]["date"]):
        out.append(curve[-1])
    return out


def run_benchmark(symbols: list[dict], equity0: float, p: dict) -> dict:
    series = {}
    sources = {}
    errors = {}
    for u in symbols:
        code = u["code"]
        print(f"[bm] fetch {code} {u.get('ticker')} {u['name']} 主力连续")
        try:
            hist, meta = load_main(u)
            series[code] = {"meta": u, "hist": hist}
            sources[code] = {k: v for k, v in meta.items() if k != "code"}
        except Exception as exc:
            errors[code] = str(exc)[:200]
            print(f"  ERR {exc}")

    print("[bm] carry curves, sina delivery months, iFinD only if <2 contracts")
    curves = load_curves([u["code"] for u in symbols])

    date_hits = Counter()
    for s in series.values():
        for bar in s["hist"]:
            date_hits[bar["date"]] += 1
    min_cover = max(3, len(series) // 3)
    dates = sorted(d for d, c in date_hits.items() if c >= min_cover)
    if len(dates) <= WARMUP + 5:
        return {"ok": False, "error": "history shorter than 250-day warmup", "errors": errors}

    idx = {code: {bar["date"]: i for i, bar in enumerate(s["hist"])} for code, s in series.items()}
    trade_dates = dates[WARMUP:]
    pos: dict[str, dict[str, int]] = {}
    day_pnls = []
    sleeve_names = ("slow", "fast", "carry")

    for di, d in enumerate(trade_dates):
        prev_d = trade_dates[di - 1] if di else None
        sleeve_pnl = {name: 0.0 for name in sleeve_names}
        day_cost = 0.0
        sizing_eq = equity0
        if day_pnls and p["compound"]:
            sizing_eq = compound_equity(
                equity0 + sum(r["pnl"] for r in day_pnls), equity0, True
            )
        day_risk = risk_budget_yuan(sizing_eq, p["risk_pct"], p["l1_mult"])

        if prev_d is not None:
            for code, sleeves in pos.items():
                i1 = idx[code].get(d)
                i0 = idx[code].get(prev_d)
                if i1 is None or i0 is None:
                    continue
                hist = series[code]["hist"]
                mult = series[code]["meta"]["mult"]
                delta = hist[i1]["close"] - hist[i0]["close"]
                for name in sleeve_names:
                    lots = sleeves.get(name) or 0
                    if lots:
                        sleeve_pnl[name] += delta * mult * lots

        raw = []
        for code, s in series.items():
            i = idx[code].get(d)
            if i is None or i < WARMUP:
                continue
            hist = s["hist"]
            atr = atr14(hist, i)
            if atr is None or atr <= 0:
                continue
            r120, r250 = ret_n(hist, i, SLOW[0]), ret_n(hist, i, SLOW[1])
            r20, r60 = ret_n(hist, i, FAST[0]), ret_n(hist, i, FAST[1])
            slow_dir = _same_sign(r120, r250)
            fast_dir = 0
            if (
                r20 is not None
                and r60 is not None
                and abs(r20) >= p["min_r20"]
                and abs(r60) >= p["min_r60"]
            ):
                fast_dir = _same_sign(r20, r60)
            if slow_dir and fast_dir == -slow_dir:
                fast_dir = 0
            carry_dir, gap = _carry_dir((curves.get(code) or {}).get("carry", {}).get(d))
            mult = s["meta"]["mult"]
            sleeves = {
                "slow": slow_dir * _lots(day_risk, atr, mult),
                "fast": fast_dir * _lots(day_risk * FAST_RISK_SHARE, atr, mult),
                "carry": carry_dir * _lots(day_risk, atr, mult),
            }
            if not any(sleeves.values()):
                continue
            slow_strength = abs(r120 or 0) + abs(r250 or 0)
            fast_strength = abs(r20 or 0) + abs(r60 or 0)
            raw.append(
                {
                    "code": code,
                    "bucket": s["meta"].get("bucket") or "_",
                    "close": hist[i]["close"],
                    "mult": mult,
                    "atr": atr,
                    "sleeves": sleeves,
                    "rank": (
                        1 if slow_dir else 0,
                        slow_strength,
                        1 if fast_dir else 0,
                        fast_strength,
                        abs(gap or 0),
                    ),
                }
            )

        raw.sort(key=lambda row: row["rank"], reverse=True)
        picked = []
        buckets: dict[str, int] = {}
        for row in raw:
            if len(picked) >= p["max_positions"]:
                break
            if p["max_per_bucket"] > 0 and buckets.get(row["bucket"], 0) >= p["max_per_bucket"]:
                continue
            picked.append(row)
            buckets[row["bucket"]] = buckets.get(row["bucket"], 0) + 1

        gross_cap = sizing_eq * p["max_gross_pct"] / 100.0
        risk_cap = sizing_eq * p["max_port_risk"] / 100.0
        # Add whole lots. Slow first, then fast, then carry. A 1-lot leg that
        # does not fit is skipped; scaling then flooring would turn it into 0.
        legs = []
        for row in picked:
            for name in sleeve_names:
                lots = row["sleeves"][name]
                if lots:
                    legs.append((row, name, lots))
        kept: list[tuple[dict, str, int]] = []
        for row, name, lots in legs:
            trial = kept + [(row, name, lots)]
            gross = sum(abs(n) * r["close"] * r["mult"] for r, _nm, n in trial)
            risk = sum(abs(n) * r["atr"] * r["mult"] for r, _nm, n in trial)
            if gross <= gross_cap + 1e-6 and risk <= risk_cap + 1e-6:
                kept.append((row, name, lots))
        target: dict[str, dict[str, int]] = {}
        for row, name, lots in kept:
            target.setdefault(row["code"], {n: 0 for n in sleeve_names})
            target[row["code"]][name] = lots

        codes = set(pos) | set(target)
        for code in codes:
            meta = series[code]["meta"]
            i = idx[code].get(d)
            if i is None:
                continue
            px = series[code]["hist"][i]["close"]
            old = pos.get(code) or {}
            new = target.get(code) or {}
            for name in sleeve_names:
                delta = abs((new.get(name) or 0) - (old.get(name) or 0))
                if delta:
                    cost = fill_cost(meta, px, delta)
                    day_cost += cost
                    sleeve_pnl[name] -= cost
        pos = {code: sleeves for code, sleeves in target.items() if any(sleeves.values())}
        pnl = sum(sleeve_pnl.values())
        day_pnls.append(
            {
                "date": d,
                "pnl": pnl,
                "cost": day_cost,
                "sleeve_pnl": sleeve_pnl,
                "sleeve_lots": {
                    name: sum(abs(s.get(name) or 0) for s in pos.values()) for name in sleeve_names
                },
                "held": len(pos),
            }
        )

    full = _window_stats(day_pnls, equity0, trade_dates[0], trade_dates[-1])
    return {
        "ok": True,
        "sources": sources,
        "errors": errors,
        "curve_coverage": curve_coverage(curves),
        "full": full,
        "day_pnls": day_pnls,
        "final_positions": pos,
        "bars": {code: len(s["hist"]) for code, s in series.items()},
    }


def _base_day_pnls(out: dict) -> list[dict]:
    rows = []
    prev = out.get("equity_start")
    for row in out.get("equity_curve") or []:
        pnl = row["equity"] - prev
        rows.append({"date": row["date"], "pnl": pnl})
        prev = row["equity"]
    return rows


def main() -> int:
    reset_usage()
    p = _load_cfg()
    yday = _yesterday()
    print(
        f"[bm] asof<={yday} equity0={p['equity0']} risk={p['risk_pct']}% "
        f"fast_share={FAST_RISK_SHARE:.3f} carry_min={CARRY_MIN:.3%} "
        f"slow={SLOW} caps={p['max_positions']}/{p['max_gross_pct']}%/{p['max_port_risk']}%"
    )
    bench = run_benchmark(p["cfg"]["symbols"], p["equity0"], p)
    print("[bm] pathA base on the same main-continuous feed")
    base = simulate(
        p["cfg"]["symbols"],
        p["equity0"],
        compound=p["compound"],
        risk_pct=p["risk_pct"],
        l1_mult=p["l1_mult"],
        max_positions=p["max_positions"],
        max_gross_pct=p["max_gross_pct"],
        max_port_risk=p["max_port_risk"],
        max_per_bucket=p["max_per_bucket"],
        min_r20=p["min_r20"],
        min_r60=p["min_r60"],
        reward_rr=p["reward_rr"],
        stop_atr_mult=p["stop_atr_mult"],
        mode="base",
    )
    rep = usage_report()
    if not bench.get("ok") or not base.get("ok"):
        print(json.dumps({"benchmark": bench.get("error"), "base": base.get("error"), "ifind_calls": rep["count"]}, ensure_ascii=False))
        return 1

    start, end = base["start"], min(base["end"], yday)
    window = _window_stats(bench["day_pnls"], p["equity0"], start, end)
    base_rows = [r for r in _base_day_pnls(base) if start <= r["date"] <= end]
    bench_map = {r["date"]: r["pnl"] for r in bench["day_pnls"] if start <= r["date"] <= end}
    paired_b, paired_a = [], []
    for row in base_rows:
        if row["date"] in bench_map:
            paired_a.append(row["pnl"])
            paired_b.append(bench_map[row["date"]])
    corr = _pearson(paired_b, paired_a)
    beats = window["ret_pct"] > base["ret_pct"] and window["max_dd_pct"] < base["max_dd_pct"]
    window_rows = [r for r in bench["day_pnls"] if start <= r["date"] <= end]
    equity_curve = _equity_curve_from_day_pnls(window_rows, p["equity0"])
    out = {
        "ok": True,
        "asof": yday,
        "contract": "主力连续",
        "data_source": "sina+tencent primary, iFinD fills gaps",
        "rules": {
            "slow": "120日与250日收益同向，风险预算100%",
            "fast": "20/60同向且过3%/5%门槛，风险预算为慢趋势的1/3；不得逆慢趋势",
            "carry": "近月高于次月0.5%做多，低于0.5%做空；与趋势分开记账",
            "caps": "最多3个品种，单板块1个，名义敞口50%，组合ATR风险8%",
            "cost": "换仓差额按每边1跳加申万2026-09-02手续费",
            "exit": "信号消失即平该层。对照组合没有1R止损和2R止盈；路径A base仍用ATR止损止盈",
        },
        "window": {
            "benchmark": window,
            "path_a_base": {
                "start": base["start"],
                "end": base["end"],
                "trade_days": base["trade_days"],
                "ret_pct": base["ret_pct"],
                "max_dd_pct": base["max_dd_pct"],
                "gross_ret_pct": base["gross_ret_pct"],
                "cost_yuan": base["cost_yuan"],
                "closed_trades": base["closed_trades"],
            },
            "daily_pnl_corr": None if corr is None else round(corr, 3),
            "beats_base_on_net_and_drawdown": beats,
        },
        "equity_start": p["equity0"],
        "equity_curve": equity_curve,
        "equity_curve_weekly": _downsample_weekly(equity_curve),
        "full_after_250_warmup": bench["full"],
        "sources": bench["sources"],
        "curve_coverage": bench["curve_coverage"],
        "final_positions": bench["final_positions"],
        "errors": bench["errors"],
        "ifind_calls": rep["count"],
        "ifind_call_log": rep["calls"],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    path = ROOT / "benchmark_latest.json"
    path.write_text(text, encoding="utf-8")
    arch = ROOT / "archive"
    arch.mkdir(exist_ok=True)
    (arch / f"benchmark_{yday.replace('-', '')}.json").write_text(text, encoding="utf-8")
    print(
        f"[bm] window {start}→{end} benchmark {window['ret_pct']:+.2f}% "
        f"DD {window['max_dd_pct']:.2f}% | pathA base {base['ret_pct']:+.2f}% "
        f"DD {base['max_dd_pct']:.2f}% corr={out['window']['daily_pnl_corr']} "
        f"beats={beats}"
    )
    print(
        f"[bm] sleeves window slow={window['pnl_by_sleeve']['slow']:.0f} "
        f"({window['days_with_sleeve']['slow']}d) "
        f"fast={window['pnl_by_sleeve']['fast']:.0f} "
        f"({window['days_with_sleeve']['fast']}d) "
        f"carry={window['pnl_by_sleeve']['carry']:.0f} "
        f"({window['days_with_sleeve']['carry']}d) cost={window['cost_yuan']:.0f}"
    )
    print(
        f"[bm] full {bench['full']['start']}→{bench['full']['end']} "
        f"{bench['full']['ret_pct']:+.2f}% DD {bench['full']['max_dd_pct']:.2f}%"
    )
    print(f"[ifind] calls={rep['count']}")
    for row in rep["calls"]:
        q = str(row.get("query") or "").replace("\n", " ")
        print(f"  - {row.get('server')}/{row.get('tool')} {q[:120]}")
    print(f"[bm] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
