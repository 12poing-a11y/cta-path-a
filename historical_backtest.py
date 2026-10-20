# -*- coding: utf-8 -*-
"""Path-A historical paper backtest from iFinD dominant-contract daily bars."""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ifind_call import call  # noqa: E402

LOOKBACK_DAYS = 120
WARMUP = 60


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
        a, b, c = _to_float(m.group(2)), _to_float(m.group(3)), _to_float(m.group(4))
        if a is None:
            continue
        vals = [v for v in (a, b, c) if v is not None]
        if len(vals) >= 3:
            high, low, cl = vals[0], vals[1], vals[2]
            if high < low:
                high, low = low, high
            hist.append({"date": d, "high": high, "low": low, "close": cl})
        elif len(vals) == 1:
            hist.append({"date": d, "high": vals[0], "low": vals[0], "close": vals[0]})
    # dedupe by date keep last
    by = {}
    for h in hist:
        by[h["date"]] = h
    return [by[k] for k in sorted(by)]


def fetch_history(name: str, n: int = LOOKBACK_DAYS):
    q = (
        f"{name}主力合约最近{n}个交易日的日期、最高价、最低价、收盘价列表，"
        f"按日期升序，尽量完整给出每一日"
    )
    ans = _answer_text(call("future", "future_quotes", {"query": q}))
    hist = _parse_ohlc_history(ans)
    if len(hist) < WARMUP + 5:
        # fallback shorter ask
        ans2 = _answer_text(
            call(
                "future",
                "future_quotes",
                {"query": f"{name}主力近{n}日收盘价序列（日期+收盘）"},
            )
        )
        hist2 = _parse_ohlc_history(ans2)
        if len(hist2) > len(hist):
            hist = hist2
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


def simulate(symbols, risk_budget, equity0):
    # fetch all
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

    # align by date union
    dates = sorted({h["date"] for s in series.values() for h in s["hist"]})
    if len(dates) < WARMUP + 5:
        return {
            "ok": False,
            "error": "history too short",
            "errors": errors,
            "bars": {k: len(v["hist"]) for k, v in series.items()},
        }

    # index maps
    idx = {
        code: {h["date"]: i for i, h in enumerate(s["hist"])}
        for code, s in series.items()
    }

    equity = equity0
    peak = equity
    max_dd = 0.0
    curve = []
    day_pnls = []
    pos = {}  # code -> {dir, lots, entry_i}

    trade_dates = dates[WARMUP:]
    for di, d in enumerate(trade_dates):
        # mark-to-market previous positions using today's close vs yesterday
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

        # recompute target positions at close d
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
                "codes": sorted(pos.keys()),
            }
        )

    wins = sum(1 for x in day_pnls if x["pnl"] > 0)
    n = len(day_pnls)
    ret_pct = (equity / equity0 - 1) * 100
    if max_dd >= 20:
        conclusion = "暂停"
    elif max_dd >= 12 or ret_pct <= -5:
        conclusion = "减仓观察"
    else:
        conclusion = "继续L1"

    return {
        "ok": True,
        "schema_version": "cta-backtest-v1",
        "start": trade_dates[0],
        "end": trade_dates[-1],
        "trade_days": n,
        "equity_start": equity0,
        "equity_end": round(equity, 2),
        "ret_pct": round(ret_pct, 3),
        "max_dd_pct": round(max_dd, 3),
        "win_rate": round(wins / n * 100, 2) if n else None,
        "conclusion": conclusion,
        "errors": errors,
        "bars": {k: len(v["hist"]) for k, v in series.items()},
        "final_positions": pos,
        "equity_curve": curve[-60:],
        "day_pnls_tail": day_pnls[-20:],
        "summary": (
            f"{trade_dates[0]}→{trade_dates[-1]} 权益 {equity:.0f}（{ret_pct:+.2f}%），"
            f"MaxDD {max_dd:.2f}%，日胜率 {(wins/n*100 if n else 0):.1f}%（{n}日），"
            f"结论 {conclusion}"
        ),
    }


def main():
    cfg, equity0, risk_budget = _load_cfg()
    print(f"[bt] equity={equity0} risk_budget={risk_budget} n={len(cfg['symbols'])}")
    out = simulate(cfg["symbols"], risk_budget, equity0)
    path = ROOT / "historical_backtest_latest.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    arch = ROOT / "archive"
    arch.mkdir(exist_ok=True)
    if out.get("end"):
        (arch / f"backtest_{out['end'].replace('-', '')}.json").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    print(out.get("summary") or out.get("error"))
    print(f"[bt] wrote {path}")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
