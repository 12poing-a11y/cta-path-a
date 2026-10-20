# -*- coding: utf-8 -*-
"""Path-A historical paper backtest (~1y) for small-capital liquid universe."""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ifind_call import call  # noqa: E402

# ~1 calendar year of trading days + warmup buffer
LOOKBACK_DAYS = 280
WARMUP = 60
BATCH_LABEL = "2026一年"


def _load_cfg():
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    equity = float(cfg.get("equity", 200_000))
    risk_pct = float(cfg.get("risk_pct", 1.5))
    l1_mult = float(cfg.get("l1_mult", 1.0))
    return cfg, equity, equity * risk_pct / 100.0 * l1_mult


def _answer_text(res: dict) -> str:
    if not res.get("ok"):
        raise RuntimeError(json.dumps(res, ensure_ascii=False)[:400])
    text = res["data"]["result"]["content"][0]["text"]
    try:
        payload = json.loads(text)
        return payload.get("data", {}).get("answer", text)
    except Exception:
        return text


def _to_float(x):
    if x is None:
        return None
    s = str(x).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "—", "NA", "N/A"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _looks_like_yyyymmdd(n: float | None) -> bool:
    if n is None:
        return False
    if abs(n - round(n)) > 1e-9:
        return False
    v = int(round(n))
    if not (20000101 <= v <= 20991231):
        return False
    mm, dd = (v // 100) % 100, v % 100
    return 1 <= mm <= 12 and 1 <= dd <= 31


def _price_num(x) -> float | None:
    n = _to_float(x)
    if n is None or _looks_like_yyyymmdd(n) or abs(n) >= 5_000_000:
        return None
    return n


def _parse_ohlc_history(ans: str):
    hist = []
    for line in ans.splitlines():
        m = re.search(
            r"(20\d{2}[-/]?\d{1,2}[-/]?\d{1,2}).{0,60}?(\d+\.?\d*).{0,30}?(\d+\.?\d*).{0,30}?(\d+\.?\d*)",
            line,
        )
        if not m:
            continue
        d = m.group(1).replace("/", "-")
        if len(d) == 8 and d.isdigit():
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        a, b, c = _price_num(m.group(2)), _price_num(m.group(3)), _price_num(m.group(4))
        vals = [v for v in (a, b, c) if v is not None]
        if len(vals) >= 3:
            high, low, cl = vals[0], vals[1], vals[2]
            if high < low:
                high, low = low, high
            hist.append({"date": d, "high": high, "low": low, "close": cl})
        elif len(vals) == 1:
            hist.append({"date": d, "high": vals[0], "low": vals[0], "close": vals[0]})
    by = {}
    for h in hist:
        by[h["date"]] = h
    return [by[k] for k in sorted(by)]


def fetch_history(name: str, n: int = LOOKBACK_DAYS):
    q = (
        f"{name}主力合约最近{n}个交易日的日期、最高价、最低价、收盘价列表，"
        f"按日期升序，尽量完整给出每一日，不要用YYYYMMDD冒充价格"
    )
    ans = _answer_text(call("future", "future_quotes", {"query": q}))
    hist = _parse_ohlc_history(ans)
    if len(hist) < WARMUP + 20:
        ans2 = _answer_text(
            call(
                "future",
                "future_quotes",
                {"query": f"{name}主力近{n}日收盘价序列（日期+收盘），按日列出"},
            )
        )
        hist2 = _parse_ohlc_history(ans2)
        if len(hist2) > len(hist):
            hist = hist2
            ans = ans2
    # second chunk if still short (model often truncates)
    if len(hist) < 150:
        first = hist[0]["date"] if hist else None
        q3 = f"{name}主力从{first or '一年前'}起再往后补全交易日收盘价列表（日期+最高+最低+收盘）"
        try:
            ans3 = _answer_text(call("future", "future_quotes", {"query": q3}))
            hist3 = _parse_ohlc_history(ans3)
            by = {h["date"]: h for h in hist}
            for h in hist3:
                by[h["date"]] = h
            hist = [by[k] for k in sorted(by)]
        except Exception:
            pass
    return hist, ans[:200]


def atr14(hist, i):
    if i < 14:
        return None
    trs = []
    for j in range(i - 13, i + 1):
        h, l, pc = hist[j]["high"], hist[j]["low"], hist[j - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / 14.0


def ret_n(hist, i, n):
    if i < n:
        return None
    a, b = hist[i - n]["close"], hist[i]["close"]
    if not a:
        return None
    return (b / a - 1.0) * 100.0


def _downsample_weekly(curve: list[dict]) -> list[dict]:
    if not curve:
        return []
    out = []
    last_week = None
    for row in curve:
        # ISO week key
        key = row["date"][:8]  # YYYY-MM roughly group by month-week via date
        y, m, d = row["date"].split("-")
        week = f"{y}-W{int(d)//7}"
        if week != last_week:
            out.append(row)
            last_week = week
    if curve and (not out or out[-1]["date"] != curve[-1]["date"]):
        out.append(curve[-1])
    return out


def _write_equity_svg(curve: list[dict], path: Path, title: str):
    if len(curve) < 2:
        return None
    eq = [c["equity"] for c in curve]
    lo, hi = min(eq), max(eq)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    w, h, l, r, t, b = 920, 360, 56, 24, 36, 40
    pw, ph = w - l - r, h - t - b

    def x(i):
        return l + pw * (i / (len(curve) - 1))

    def y(v):
        return t + ph * (1 - (v - lo) / (hi - lo))

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(eq))
    # grid
    grids = []
    for k in range(5):
        yy = t + ph * k / 4
        val = hi - (hi - lo) * k / 4
        grids.append(
            f'<line x1="{l}" y1="{yy:.1f}" x2="{w-r}" y2="{yy:.1f}" stroke="#e5e5e5"/>'
            f'<text x="{l-8}" y="{yy+4:.1f}" text-anchor="end" font-size="11" fill="#666">{val:,.0f}</text>'
        )
    labels = []
    for i in (0, len(curve) // 2, len(curve) - 1):
        labels.append(
            f'<text x="{x(i):.1f}" y="{h-12}" text-anchor="middle" font-size="11" fill="#666">{curve[i]["date"]}</text>'
        )
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <rect width="100%" height="100%" fill="#fff"/>
  <text x="{l}" y="22" font-size="15" font-family="Segoe UI,sans-serif" fill="#111">{title}</text>
  {''.join(grids)}
  <polyline fill="none" stroke="#2563eb" stroke-width="2" points="{pts}"/>
  {''.join(labels)}
  <text x="{w/2}" y="{h-2}" text-anchor="middle" font-size="10" fill="#999">Path-A TSMOM+ATR · equity curve</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")
    return path


def simulate(symbols, risk_budget, equity0):
    series = {}
    errors = {}
    for u in symbols:
        code = u["code"]
        print(f"[bt] fetch history {code} {u['name']}...")
        try:
            hist, _ = fetch_history(u["name"])
            series[code] = {"meta": u, "hist": hist}
            print(f"  bars={len(hist)}")
        except Exception as e:
            errors[code] = str(e)[:200]
            print(f"  ERR {e}")

    dates = sorted({h["date"] for s in series.values() for h in s["hist"]})
    if len(dates) < WARMUP + 5:
        return {
            "ok": False,
            "error": "history too short",
            "errors": errors,
            "bars": {k: len(v["hist"]) for k, v in series.items()},
        }

    idx = {
        code: {h["date"]: i for i, h in enumerate(s["hist"])}
        for code, s in series.items()
    }

    equity = equity0
    peak = equity
    max_dd = 0.0
    curve = []
    day_pnls = []
    pos = {}

    trade_dates = dates[WARMUP:]
    for di, d in enumerate(trade_dates):
        pnl = 0.0
        if di > 0:
            prev_d = trade_dates[di - 1]
            for code, p in list(pos.items()):
                hist = series[code]["hist"]
                i0 = idx[code].get(prev_d)
                i1 = idx[code].get(d)
                if i0 is None or i1 is None:
                    continue
                mult = series[code]["meta"]["mult"]
                sign = 1 if p["direction"] == "多" else -1
                pnl += (hist[i1]["close"] - hist[i0]["close"]) * mult * p["lots"] * sign
        equity += pnl
        day_pnls.append({"date": d, "pnl": round(pnl, 2), "equity": round(equity, 2)})
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak else 0
        max_dd = max(max_dd, dd)

        new_pos = {}
        for code, s in series.items():
            i = idx[code].get(d)
            if i is None or i < WARMUP:
                continue
            hist = s["hist"]
            r20, r60 = ret_n(hist, i, 20), ret_n(hist, i, 60)
            a = atr14(hist, i)
            if r20 is None or r60 is None or a is None or a <= 0:
                continue
            if not ((r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0)):
                continue
            direction = "多" if r20 > 0 else "空"
            risk_per_lot = a * s["meta"]["mult"]
            lots = int(math.floor(risk_budget / risk_per_lot))
            if lots <= 0:
                continue
            new_pos[code] = {
                "direction": direction,
                "lots": lots,
                "atr": round(a, 2),
                "r20": round(r20, 3),
                "r60": round(r60, 3),
            }
        pos = new_pos
        curve.append(
            {
                "date": d,
                "equity": round(equity, 2),
                "held": len(pos),
                "pnl": round(pnl, 2),
                "dd_pct": round(dd, 3),
                "codes": sorted(pos.keys()),
            }
        )

    wins = sum(1 for x in day_pnls if x["pnl"] > 0)
    n = len(day_pnls)
    ret_pct = (equity / equity0 - 1) * 100
    avg_held = (sum(c["held"] for c in curve) / len(curve)) if curve else 0
    if max_dd >= 20:
        conclusion = "暂停"
    elif max_dd >= 12 or ret_pct <= -5:
        conclusion = "减仓观察"
    else:
        conclusion = "继续L1"

    pool = ",".join(u["code"] for u in symbols)
    return {
        "ok": True,
        "schema_version": "cta-backtest-v2-1y",
        "batch": BATCH_LABEL,
        "universe_n": len(symbols),
        "universe": pool,
        "start": trade_dates[0],
        "end": trade_dates[-1],
        "trade_days": n,
        "equity_start": equity0,
        "equity_end": round(equity, 2),
        "ret_pct": round(ret_pct, 3),
        "max_dd_pct": round(max_dd, 3),
        "win_rate": round(wins / n * 100, 2) if n else None,
        "avg_held": round(avg_held, 2),
        "conclusion": conclusion,
        "errors": errors,
        "bars": {k: len(v["hist"]) for k, v in series.items()},
        "final_positions": pos,
        "equity_curve": curve,
        "equity_curve_weekly": _downsample_weekly(curve),
        "day_pnls_tail": day_pnls[-20:],
        "summary": (
            f"{trade_dates[0]}→{trade_dates[-1]} 权益 {equity:.0f}（{ret_pct:+.2f}%），"
            f"MaxDD {max_dd:.2f}%，日胜率 {(wins/n*100 if n else 0):.1f}%（{n}日），"
            f"均持仓 {avg_held:.1f}，池 {len(symbols)} 品种，结论 {conclusion}"
        ),
    }


def main():
    cfg, equity0, risk_budget = _load_cfg()
    print(f"[bt] equity={equity0} risk_budget={risk_budget} n={len(cfg['symbols'])} lookback={LOOKBACK_DAYS}")
    out = simulate(cfg["symbols"], risk_budget, equity0)
    path = ROOT / "historical_backtest_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    arch = ROOT / "archive"
    arch.mkdir(exist_ok=True)
    if out.get("end"):
        (arch / f"backtest_{out['end'].replace('-', '')}.json").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    chart = ROOT / "historical_equity_curve.svg"
    if out.get("ok") and out.get("equity_curve"):
        _write_equity_svg(
            out["equity_curve"],
            chart,
            f"CTA Path-A 一年权益曲线 {out.get('start')}→{out.get('end')}",
        )
        print(f"[bt] chart {chart}")
    print(out.get("summary") or out.get("error"))
    print(f"[bt] wrote {path}")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
