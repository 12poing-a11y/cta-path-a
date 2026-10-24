# -*- coding: utf-8 -*-
"""Paper applicability of vnpy CTA demo strategies on Path-A daily bars.

Uses default parameters from ``vnpy_ctastrategy`` demos. Daily bars approximate
15m/5m/intraday templates — DualThrust / MultiTimeframe / KingKeltner / Boll
are **degraded** vs original bar period. TestStrategy is skipped (order API probe).

Writes ``lab/research/oos/vnpy_cta_applicability_latest.json``.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from historical_backtest import _fetch_pack, _load_cfg  # noqa: E402
from path_a_filters import fill_cost  # noqa: E402

OUT = ROOT / "lab" / "research" / "oos" / "vnpy_cta_applicability_latest.json"
START = "2025-11-27"


def _sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if n <= 0 or len(x) < n:
        return out
    c = np.cumsum(x, dtype=float)
    out[n - 1 :] = (c[n - 1 :] - np.concatenate([[0.0], c[:-n]])) / n
    return out


def _atr(h, l, c, n: int) -> np.ndarray:
    tr = np.zeros(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return _sma(tr, n)


def _rsi(c: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(c, np.nan, dtype=float)
    if len(c) < n + 1:
        return out
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    for i in range(n, len(c)):
        au = up[i - n : i].mean()
        ad = dn[i - n : i].mean()
        if ad <= 1e-12:
            out[i] = 100.0
        else:
            rs = au / ad
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _cci(h, l, c, n: int) -> np.ndarray:
    tp = (h + l + c) / 3.0
    out = np.full_like(c, np.nan, dtype=float)
    for i in range(n - 1, len(c)):
        window = tp[i - n + 1 : i + 1]
        m = window.mean()
        md = np.mean(np.abs(window - m))
        out[i] = 0.0 if md <= 1e-12 else (tp[i] - m) / (0.015 * md)
    return out


def _boll(c: np.ndarray, n: int, dev: float) -> tuple[np.ndarray, np.ndarray]:
    mid = _sma(c, n)
    up = np.full_like(c, np.nan)
    dn = np.full_like(c, np.nan)
    for i in range(n - 1, len(c)):
        sd = c[i - n + 1 : i + 1].std(ddof=0)
        up[i] = mid[i] + dev * sd
        dn[i] = mid[i] - dev * sd
    return up, dn


def _donchian(h, l, n: int) -> tuple[np.ndarray, np.ndarray]:
    up = np.full_like(h, np.nan)
    dn = np.full_like(l, np.nan)
    for i in range(n - 1, len(h)):
        up[i] = h[i - n + 1 : i + 1].max()
        dn[i] = l[i - n + 1 : i + 1].min()
    return up, dn


def _keltner(h, l, c, n: int, dev: float) -> tuple[np.ndarray, np.ndarray]:
    mid = _sma(c, n)
    atr = _atr(h, l, c, n)
    return mid + dev * atr, mid - dev * atr


@dataclass
class TradeBook:
    pos: int = 0
    entry: float = 0.0
    trail_hi: float = 0.0
    trail_lo: float = 0.0
    stop: float = 0.0


def _equity_stats(curve: list[float]) -> dict:
    if len(curve) < 2:
        return {"ret_pct": None, "max_dd_pct": None, "calmar": None}
    ret = (curve[-1] / curve[0] - 1.0) * 100.0
    peak = curve[0]
    max_dd = 0.0
    for e in curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak * 100.0)
    calmar = round(ret / max_dd, 3) if max_dd > 0 else None
    return {"ret_pct": round(ret, 3), "max_dd_pct": round(max_dd, 3), "calmar": calmar}


def _run_symbol(
    name: str,
    hist: list[dict],
    meta: dict,
    *,
    start: str,
    equity0: float = 50_000.0,
) -> dict:
    """1-lot round-turn paper on one continuous series. Returns equity curve + trades."""
    dates = [h["date"] for h in hist]
    o = np.array([float(h.get("open") or h["close"]) for h in hist], dtype=float)
    h = np.array([float(h.get("high") or h["close"]) for h in hist], dtype=float)
    l = np.array([float(h.get("low") or h["close"]) for h in hist], dtype=float)
    c = np.array([float(h["close"]) for h in hist], dtype=float)
    n = len(c)
    if n < 80:
        return {"ok": False, "error": "bars_short"}

    # Precompute indicators used by multiple rules
    sma10, sma20 = _sma(c, 10), _sma(c, 20)
    sma5 = _sma(c, 5)
    atr22 = _atr(h, l, c, 22)
    atr_ma10 = _sma(np.nan_to_num(atr22, nan=0.0), 10)
    rsi5 = _rsi(c, 5)
    rsi14 = _rsi(c, 14)
    cci10 = _cci(h, l, c, 10)
    cci30 = _cci(h, l, c, 30)
    boll_up, boll_dn = _boll(c, 18, 3.4)
    atr30 = _atr(h, l, c, 30)
    kk_up, kk_dn = _keltner(h, l, c, 11, 1.6)
    don_up20, don_dn20 = _donchian(h, l, 20)
    don_up10, don_dn10 = _donchian(h, l, 10)
    atr20 = _atr(h, l, c, 20)
    # Dual thrust range from prior day
    prev_range = np.zeros(n)
    for i in range(1, n):
        prev_range[i] = h[i - 1] - l[i - 1]

    book = TradeBook()
    equity = equity0
    curve = []
    closed = []
    pending: tuple[str, int, float] | None = None  # open|close, side_or_0, ref_px
    i0 = next((i for i, d in enumerate(dates) if d >= start), None)
    if i0 is None:
        return {"ok": False, "error": "no_start"}

    def close_pos(i: int, px: float, why: str) -> None:
        nonlocal equity, book
        if book.pos == 0:
            return
        lots = abs(book.pos)
        sign = 1 if book.pos > 0 else -1
        pnl = (px - book.entry) * sign * lots * float(meta["mult"])
        cost = fill_cost(meta, book.entry, lots) + fill_cost(meta, px, lots)
        net = pnl - cost
        equity += net
        closed.append({"date": dates[i], "pnl": net, "why": why, "side": book.pos})
        book = TradeBook()

    def open_pos(i: int, side: int, px: float) -> None:
        nonlocal book
        book = TradeBook(pos=side, entry=px, trail_hi=h[i], trail_lo=l[i])

    for i in range(i0, n):
        # Fill signals from prior bar at today's open (no same-bar look-ahead).
        if pending is not None and i > i0:
            kind, side, _ref = pending
            px = float(o[i])
            if kind == "close" and book.pos != 0:
                close_pos(i, px, "signal_next_open")
            elif kind == "open" and book.pos == 0:
                open_pos(i, side, px)
            pending = None

        if book.pos != 0:
            mtm = equity + (c[i] - book.entry) * (1 if book.pos > 0 else -1) * float(meta["mult"])
            curve.append(mtm)
        else:
            curve.append(equity)

        # --- exits first (stop hits same bar OK; signal exits → next open) ---
        if book.pos != 0:
            book.trail_hi = max(book.trail_hi, h[i])
            book.trail_lo = min(book.trail_lo, l[i])
            if name == "DoubleMaStrategy":
                if book.pos > 0 and sma10[i] < sma20[i] and sma10[i - 1] >= sma20[i - 1]:
                    pending = ("close", 0, c[i])
                elif book.pos < 0 and sma10[i] > sma20[i] and sma10[i - 1] <= sma20[i - 1]:
                    pending = ("close", 0, c[i])
            elif name == "AtrRsiStrategy":
                # Daily: use 2×ATR trail (0.8% was for short bars and inflates WR).
                if math.isnan(atr22[i]):
                    pass
                elif book.pos > 0:
                    stop = book.trail_hi - 2.0 * atr22[i]
                    if l[i] <= stop:
                        close_pos(i, stop, "atr_trail")
                else:
                    stop = book.trail_lo + 2.0 * atr22[i]
                    if h[i] >= stop:
                        close_pos(i, stop, "atr_trail")
            elif name == "BollChannelStrategy":
                if math.isnan(atr30[i]):
                    pass
                elif book.pos > 0:
                    stop = book.trail_hi - atr30[i] * 5.2
                    if l[i] <= stop:
                        close_pos(i, stop, "atr_stop")
                else:
                    stop = book.trail_lo + atr30[i] * 5.2
                    if h[i] >= stop:
                        close_pos(i, stop, "atr_stop")
            elif name == "KingKeltnerStrategy":
                if math.isnan(atr20[i]):
                    pass
                elif book.pos > 0:
                    stop = book.trail_hi - 2.0 * atr20[i]
                    if l[i] <= stop:
                        close_pos(i, stop, "atr_trail")
                else:
                    stop = book.trail_lo + 2.0 * atr20[i]
                    if h[i] >= stop:
                        close_pos(i, stop, "atr_trail")
            elif name == "TurtleSignalStrategy":
                if book.pos > 0 and (not math.isnan(don_dn10[i])) and l[i] <= don_dn10[i]:
                    close_pos(i, min(c[i], don_dn10[i]), "donchian_exit")
                elif book.pos < 0 and (not math.isnan(don_up10[i])) and h[i] >= don_up10[i]:
                    close_pos(i, max(c[i], don_up10[i]), "donchian_exit")
            elif name == "DualThrustStrategy":
                rng = prev_range[i]
                if rng > 0:
                    long_e = o[i] + 0.4 * rng
                    short_e = o[i] - 0.6 * rng
                    if book.pos > 0 and l[i] <= short_e:
                        close_pos(i, short_e, "dt_flip")
                    elif book.pos < 0 and h[i] >= long_e:
                        close_pos(i, long_e, "dt_flip")
            elif name == "MultiTimeframeStrategy":
                trend = 1 if sma5[i] > sma20[i] else -1
                if book.pos > 0 and (trend < 0 or (not math.isnan(rsi14[i]) and rsi14[i] < 50)):
                    pending = ("close", 0, c[i])
                elif book.pos < 0 and (trend > 0 or (not math.isnan(rsi14[i]) and rsi14[i] > 50)):
                    pending = ("close", 0, c[i])
            elif name == "MultiSignalStrategy":
                sig = 0
                if not math.isnan(rsi14[i]):
                    if rsi14[i] >= 70:
                        sig += 1
                    elif rsi14[i] <= 30:
                        sig -= 1
                if not math.isnan(cci30[i]):
                    if cci30[i] >= 10:
                        sig += 1
                    elif cci30[i] <= -10:
                        sig -= 1
                if not math.isnan(sma5[i]) and not math.isnan(sma20[i]):
                    if sma5[i] > sma20[i]:
                        sig += 1
                    elif sma5[i] < sma20[i]:
                        sig -= 1
                target = 1 if sig >= 2 else (-1 if sig <= -2 else 0)
                if target == 0 or target != (1 if book.pos > 0 else -1):
                    pending = ("close", 0, c[i])

        if book.pos != 0 or pending is not None:
            continue

        # --- entries → next open ---
        if name == "DoubleMaStrategy":
            if (
                not math.isnan(sma10[i])
                and not math.isnan(sma20[i])
                and not math.isnan(sma10[i - 1])
            ):
                if sma10[i] > sma20[i] and sma10[i - 1] <= sma20[i - 1]:
                    pending = ("open", 1, c[i])
                elif sma10[i] < sma20[i] and sma10[i - 1] >= sma20[i - 1]:
                    pending = ("open", -1, c[i])
        elif name == "AtrRsiStrategy":
            if (
                not math.isnan(atr22[i])
                and not math.isnan(atr_ma10[i])
                and not math.isnan(rsi5[i])
                and atr22[i] > atr_ma10[i]
            ):
                if rsi5[i] > 66:
                    pending = ("open", 1, c[i])
                elif rsi5[i] < 34:
                    pending = ("open", -1, c[i])
        elif name == "BollChannelStrategy":
            if not math.isnan(cci10[i]) and not math.isnan(boll_up[i]):
                if cci10[i] > 0 and h[i] >= boll_up[i]:
                    pending = ("open", 1, boll_up[i])
                elif cci10[i] < 0 and l[i] <= boll_dn[i]:
                    pending = ("open", -1, boll_dn[i])
        elif name == "KingKeltnerStrategy":
            if not math.isnan(kk_up[i]):
                if h[i] >= kk_up[i]:
                    pending = ("open", 1, kk_up[i])
                elif l[i] <= kk_dn[i]:
                    pending = ("open", -1, kk_dn[i])
        elif name == "TurtleSignalStrategy":
            if not math.isnan(don_up20[i]):
                if h[i] >= don_up20[i]:
                    pending = ("open", 1, don_up20[i])
                elif l[i] <= don_dn20[i]:
                    pending = ("open", -1, don_dn20[i])
        elif name == "DualThrustStrategy":
            rng = prev_range[i]
            if rng > 0:
                long_e = o[i] + 0.4 * rng
                short_e = o[i] - 0.6 * rng
                if h[i] >= long_e:
                    pending = ("open", 1, long_e)
                elif l[i] <= short_e:
                    pending = ("open", -1, short_e)
        elif name == "MultiTimeframeStrategy":
            trend = 1 if (not math.isnan(sma5[i]) and sma5[i] > sma20[i]) else -1
            if not math.isnan(rsi14[i]):
                if trend > 0 and rsi14[i] >= 70:
                    pending = ("open", 1, c[i])
                elif trend < 0 and rsi14[i] <= 30:
                    pending = ("open", -1, c[i])
        elif name == "MultiSignalStrategy":
            sig = 0
            if not math.isnan(rsi14[i]):
                if rsi14[i] >= 70:
                    sig += 1
                elif rsi14[i] <= 30:
                    sig -= 1
            if not math.isnan(cci30[i]):
                if cci30[i] >= 10:
                    sig += 1
                elif cci30[i] <= -10:
                    sig -= 1
            if not math.isnan(sma5[i]) and not math.isnan(sma20[i]):
                if sma5[i] > sma20[i]:
                    sig += 1
                elif sma5[i] < sma20[i]:
                    sig -= 1
            if sig >= 2:
                pending = ("open", 1, c[i])
            elif sig <= -2:
                pending = ("open", -1, c[i])

    if book.pos != 0:
        close_pos(n - 1, c[-1], "eod")

    wins = [t for t in closed if t["pnl"] > 0]
    stats = _equity_stats(curve if curve else [equity0, equity])
    stats.update(
        {
            "ok": True,
            "equity_end": round(equity, 2),
            "closed_trades": len(closed),
            "trade_win_rate": round(len(wins) / len(closed) * 100, 2) if closed else None,
            "start": dates[i0],
            "end": dates[-1],
        }
    )
    return stats


STRATEGIES = [
    ("DoubleMaStrategy", "双均线", "日线可忠实复现", True),
    ("AtrRsiStrategy", "动量+过滤", "日线可复现（原示例常配分钟）", True),
    ("BollChannelStrategy", "通道", "原15m；日线为降采样近似", True),
    ("DualThrustStrategy", "日内突破", "原日内；日线用昨幅近似，保真度低", True),
    ("KingKeltnerStrategy", "通道", "原5m；日线降采样近似", True),
    ("TurtleSignalStrategy", "海龟", "日线可忠实复现唐奇安逻辑", True),
    ("MultiTimeframeStrategy", "多周期", "原5m+15m；日线用MA趋势+RSI近似", True),
    ("MultiSignalStrategy", "多信号合成", "日线合成 RSI/CCI/MA（MA原5m）", True),
    ("TestStrategy", "测试用", "测下单接口，不做适用性回测", False),
]


def _level(row: dict) -> str:
    if not row.get("ok"):
        return "跳过"
    calmar = row.get("calmar")
    ret = row.get("ret_pct")
    dd = row.get("max_dd_pct")
    n = row.get("closed_trades") or 0
    if n < 8:
        return "低"
    if calmar is not None and calmar >= 1.2 and ret is not None and ret > 0 and dd is not None and dd < 15:
        return "高"
    if calmar is not None and calmar >= 0.6 and ret is not None and ret > 0:
        return "中"
    if ret is not None and ret > 0 and dd is not None and dd < 12:
        return "中"
    return "低"


def main() -> int:
    p = _load_cfg()
    pack = _fetch_pack(p["cfg"]["symbols"])
    series, errors, _sources = pack
    per_strategy = []
    for name, kind, fidelity, runnable in STRATEGIES:
        if not runnable:
            per_strategy.append(
                {
                    "strategy": name,
                    "kind": kind,
                    "fidelity": fidelity,
                    "applicability": "跳过",
                    "adopt": False,
                    "reason": "非交易策略",
                }
            )
            continue
        print(f"[vnpy-cta] {name} …")
        code_rows = []
        for code, s in series.items():
            hist = [h for h in (s.get("hist") or []) if h.get("date")]
            meta = dict(s.get("meta") or {})
            # ensure fee fields
            for u in p["cfg"]["symbols"]:
                if u["code"] == code:
                    meta.update({k: u.get(k) for k in ("mult", "tick", "fee_yuan", "fee_rate")})
                    break
            one = _run_symbol(name, hist, meta, start=START)
            if one.get("ok"):
                code_rows.append({"code": code, **{k: one[k] for k in (
                    "ret_pct", "max_dd_pct", "calmar", "trade_win_rate", "closed_trades"
                )}})
        if not code_rows:
            per_strategy.append(
                {
                    "strategy": name,
                    "kind": kind,
                    "fidelity": fidelity,
                    "applicability": "低",
                    "adopt": False,
                    "reason": "无有效品种结果",
                }
            )
            continue
        # Robust portfolio proxy: median ret / median dd (AG 1-lot % 会极端拉高均值)
        rets = [r["ret_pct"] for r in code_rows if r.get("ret_pct") is not None]
        dds = [r["max_dd_pct"] for r in code_rows if r.get("max_dd_pct") is not None]
        med_ret = float(np.median(rets)) if rets else None
        med_dd = float(np.median(dds)) if dds else None
        calmar = round(med_ret / med_dd, 3) if med_ret is not None and med_dd and med_dd > 0 else None
        trades = sum(int(r.get("closed_trades") or 0) for r in code_rows)
        pos_share = sum(1 for r in code_rows if (r.get("ret_pct") or 0) > 0) / len(code_rows)
        row = {
            "strategy": name,
            "kind": kind,
            "fidelity": fidelity,
            "n_symbols": len(code_rows),
            "median_ret_pct": None if med_ret is None else round(med_ret, 3),
            "median_max_dd_pct": None if med_dd is None else round(med_dd, 3),
            "calmar_proxy": calmar,
            "closed_trades_sum": trades,
            "positive_symbol_share": round(pos_share * 100, 1),
            "by_symbol": code_rows,
        }
        row["applicability"] = _level(
            {
                "ok": True,
                "calmar": calmar,
                "ret_pct": med_ret,
                "max_dd_pct": med_dd,
                "closed_trades": trades // max(1, len(code_rows)),
            }
        )
        # Only daily-faithful + beats Path-A seats calmar (~0.86) on median proxy
        faithful = name in ("DoubleMaStrategy", "AtrRsiStrategy", "TurtleSignalStrategy", "MultiSignalStrategy")
        beats = calmar is not None and calmar >= 0.9 and med_ret is not None and med_ret > 0
        row["adopt"] = row["applicability"] in ("高", "中") and faithful and beats
        row["reason"] = (
            f"中位收益{row['median_ret_pct']}% 中位回撤{row['median_max_dd_pct']}% "
            f"Calmar≈{calmar} 盈利品种占比{row['positive_symbol_share']}%"
        )
        print(
            f"  → {row['applicability']} med_ret={row['median_ret_pct']} dd={row['median_max_dd_pct']} "
            f"calmar={calmar} adopt={row['adopt']}"
        )
        per_strategy.append(row)

    adopt_ids = [r["strategy"] for r in per_strategy if r.get("adopt")]
    report = {
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe": "Path-A 20",
        "window_start": START,
        "bar": "daily continuous (sina pack)",
        "note_zh": (
            "vnpy 官方 CTA 示例默认参数；Boll/Keltner/DualThrust/MultiTimeframe "
            "原为分钟/日内，日线仅为逻辑族适用性探测，不作实盘参数。"
        ),
        "path_a_seats_ref": {"ret_pct": 5.23, "max_dd_pct": 6.105, "calmar": 0.857, "window": "2025-11-27+"},
        "strategies": per_strategy,
        "adopt_list": adopt_ids,
        "decision_zh": (
            f"建议并入研究台纸面对照：{adopt_ids or '无（无一达到高适用且日线可忠实）'}；"
            "其余保留归档观察，不替换 Path-A seats 入场。"
        ),
        "fetch_errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run = ROOT / "lab" / "research" / "runs" / f"vnpy_cta_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run.mkdir(parents=True, exist_ok=True)
    (run / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[vnpy-cta] wrote {OUT}")
    print(f"[vnpy-cta] {report['decision_zh']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
