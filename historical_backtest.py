# -*- coding: utf-8 -*-
"""Path-A ~1y paper backtest. Sina/Tencent daily bars, iFinD if those are short."""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ifind_call import active_slot, call, usage_report  # noqa: E402
from member_rank import load_member_changes  # noqa: E402
from path_a_filters import entry_block, fill_cost  # noqa: E402
from public_curve import curve_coverage, load_curves  # noqa: E402
from position_rules import (  # noqa: E402
    apply_portfolio_caps,
    compound_equity,
    risk_budget_yuan,
)
from wyckoff_pullback import apply_stop_target  # noqa: E402

LOOKBACK_DAYS = 260
WARMUP = 60
BATCH_LABEL = "2026一年-pathA-rr2"
CUTOFF_DAYS = 420


def _load_cfg():
    cfg = json.loads((ROOT / "universe.json").read_text(encoding="utf-8"))
    equity = float(cfg.get("equity", 200_000))
    compound = bool(cfg.get("equity_compound", True))
    risk_pct = float(cfg.get("risk_pct", 1.5))
    l1_mult = float(cfg.get("l1_mult", 1.0))
    max_positions = int(cfg.get("max_positions", 3))
    max_gross_pct = float(cfg.get("max_gross_exposure_pct", 50))
    max_port_risk = float(cfg.get("max_portfolio_risk_pct", 8))
    max_per_bucket = int(cfg.get("max_per_bucket", 1))
    min_r20 = float(cfg.get("min_r20_pct", 3))
    min_r60 = float(cfg.get("min_r60_pct", 5))
    sel = cfg.get("selection") or {}
    reward_rr = float(sel.get("reward_rr") or cfg.get("reward_rr") or 2)
    stop_atr_mult = float(sel.get("stop_atr_mult") or cfg.get("stop_atr_mult") or 1)
    return {
        "cfg": cfg,
        "equity0": equity,
        "compound": compound,
        "risk_pct": risk_pct,
        "l1_mult": l1_mult,
        "max_positions": max_positions,
        "max_gross_pct": max_gross_pct,
        "max_port_risk": max_port_risk,
        "max_per_bucket": max_per_bucket,
        "min_r20": min_r20,
        "min_r60": min_r60,
        "reward_rr": reward_rr,
        "stop_atr_mult": stop_atr_mult,
        "entry_filter": cfg.get("entry_filter") or "base",
    }


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
    if s in ("", "-", "—", "NA", "N/A", "\t"):
        return None
    # 成交量 occasionally like 101.96万
    m = re.match(r"^(-?\d+\.?\d*)\s*万$", s)
    if m:
        return float(m.group(1)) * 10_000
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


def _norm_date(s: str) -> str | None:
    s = str(s or "").strip()
    if re.fullmatch(r"20\d{6}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if re.fullmatch(r"20\d{2}-\d{1,2}-\d{1,2}", s):
        y, m, d = s.split("-")
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return None


def _col_key(h: str) -> str:
    h = str(h or "").strip().lower()
    if "日期" in h or h in ("date", "time"):
        return "date"
    if "开盘" in h or h == "open":
        return "open"
    if "最高" in h or h == "high":
        return "high"
    if "最低" in h or h == "low":
        return "low"
    if "收盘" in h or h in ("close", "settle", "结算"):
        return "close"
    if "成交量" in h or "volume" in h or "量" == h:
        return "volume"
    if "成交额" in h or "amount" in h:
        return "amount"
    if "代码" in h or "code" in h:
        return "code"
    if "名称" in h or "name" in h:
        return "name"
    return h


def _parse_md_tables(ans: str) -> list[list[dict]]:
    """Parse all markdown tables into list of row dicts keyed by normalized headers."""
    lines = [ln.strip() for ln in ans.splitlines()]
    tables = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("|"):
            i += 1
            continue
        block = []
        while i < len(lines) and lines[i].startswith("|"):
            block.append(lines[i])
            i += 1
        if len(block) < 2:
            continue
        headers = [c.strip() for c in block[0].strip("|").split("|")]
        body = block[1:]
        if body and re.match(r"^\|[\s\-:|]+\|$", body[0]):
            body = body[1:]
        rows = []
        for ln in body:
            if re.match(r"^\|[\s\-:|]+\|$", ln):
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) < 2:
                continue
            row = {}
            for j, h in enumerate(headers):
                if j >= len(cells):
                    break
                row[_col_key(h)] = cells[j]
            rows.append(row)
        if rows:
            tables.append(rows)
    return tables


def _row_to_bar(row: dict) -> dict | None:
    d = _norm_date(row.get("date") or "")
    if not d:
        # sometimes date is a bare YYYYMMDD in a wrong column
        for v in row.values():
            d = _norm_date(str(v))
            if d:
                break
    if not d:
        return None
    close = _to_float(row.get("close"))
    high = _to_float(row.get("high"))
    low = _to_float(row.get("low"))
    open_ = _to_float(row.get("open"))
    # if only one price field filled, use it
    prices = [p for p in (close, high, low, open_) if p is not None and not _looks_like_yyyymmdd(p)]
    if not prices:
        return None
    if close is None or _looks_like_yyyymmdd(close):
        close = prices[-1]
    if high is None or _looks_like_yyyymmdd(high):
        high = max(prices)
    if low is None or _looks_like_yyyymmdd(low):
        low = min(prices)
    if not (50 <= abs(close) <= 200_000):
        return None
    if high < low:
        high, low = low, high
    if high / max(low, 1e-9) > 5:
        return None
    return {
        "date": d,
        "high": high,
        "low": low,
        "close": close,
        "volume": _to_float(row.get("volume")),
    }


def _parse_zl_history(ans: str) -> list[dict]:
    bars = {}
    for table in _parse_md_tables(ans):
        for row in table:
            bar = _row_to_bar(row)
            if bar:
                bars[bar["date"]] = bar
    # fallback regex for date + 3 numbers (legacy)
    if len(bars) < 10:
        for line in ans.splitlines():
            m = re.search(
                r"(20\d{6}|20\d{2}-\d{1,2}-\d{1,2}).{0,80}?(\d+\.?\d*).{0,40}?(\d+\.?\d*).{0,40}?(\d+\.?\d*)",
                line,
            )
            if not m:
                continue
            d = _norm_date(m.group(1))
            nums = [_to_float(m.group(i)) for i in (2, 3, 4)]
            nums = [n for n in nums if n is not None and not _looks_like_yyyymmdd(n) and 50 <= abs(n) <= 200_000]
            if not d or len(nums) < 1:
                continue
            if len(nums) >= 3:
                high, low, cl = nums[0], nums[1], nums[2]
            else:
                high = low = cl = nums[0]
            if high < low:
                high, low = low, high
            bars[d] = {"date": d, "high": high, "low": low, "close": cl, "volume": None}
    cutoff = (date.today() - timedelta(days=CUTOFF_DAYS)).isoformat()
    out = [bars[k] for k in sorted(bars) if k >= cutoff]
    return out


def _fetch_ifind_history(u: dict, n: int = LOOKBACK_DAYS):
    """iFinD 主力连续 fallback. Used only when Sina and Tencent are not enough."""
    name = u["name"]
    ticker = u.get("ticker") or ""
    by = {}
    last_ans = ""

    # Prefer ticker-targeted monthly/quarterly chunks
    today = date.today()
    cursor = today.replace(day=1)
    chunks = []
    for _ in range(5):
        y, m = cursor.year, cursor.month
        m0 = m - 2
        y0 = y
        while m0 <= 0:
            m0 += 12
            y0 -= 1
        chunks.append((f"{y0}-{m0:02d}", f"{y}-{m:02d}"))
        m -= 3
        while m <= 0:
            m += 12
            y -= 1
        cursor = date(y, m, 1)

    for start_ym, end_ym in reversed(chunks):
        q = (
            f"证券代码{ticker}（{name}主力连续）从{start_ym}到{end_ym}每个交易日的"
            f"日期、开盘价、最高价、最低价、收盘价、成交量。"
            f"一张Markdown表；日期用YYYYMMDD或YYYY-MM-DD；价格为真实行情。"
        )
        try:
            ans = _answer_text(call("future", "future_quotes", {"query": q}))
            last_ans = ans
            for h in _parse_zl_history(ans):
                by[h["date"]] = h
            print(f"    {ticker} chunk {start_ym}->{end_ym} bars={len(by)}")
        except Exception as e:
            print(f"    {ticker} chunk fail {start_ym}: {e}")

    if len(by) < WARMUP + 20:
        q2 = (
            f"{ticker} {name}主力连续最近{n}个交易日日期、最高价、最低价、收盘价、成交量，"
            f"Markdown表"
        )
        try:
            ans2 = _answer_text(call("future", "future_quotes", {"query": q2}))
            last_ans = ans2
            for h in _parse_zl_history(ans2):
                by[h["date"]] = h
        except Exception as e:
            print(f"    fallback fail: {e}")

    hist = [by[k] for k in sorted(by)]
    return hist


def fetch_history(u: dict, n: int = LOOKBACK_DAYS):
    """Sina + Tencent first. iFinD fills missing dates when that set is short or stale."""
    from market_data import load_free_bars, merge_bars, series_sufficient, trim_bars

    code = u.get("code") or ""
    free, meta = load_free_bars(code)
    need = max(80, WARMUP + 20)
    if series_sufficient(free, need):
        bars = free
        meta["ifind"] = False
    else:
        ifind = _fetch_ifind_history(u, n)
        bars = merge_bars(free, ifind)
        meta["ifind_n"] = len(ifind)
        meta["ifind"] = True
        meta["source"] = (meta.get("source") + "+ifind") if meta.get("source") else "ifind"
    bars = trim_bars(bars, CUTOFF_DAYS)
    meta["bars"] = len(bars)
    print(
        f"  source={meta.get('source')} sina={meta.get('sina_n')} "
        f"tencent={meta.get('tencent_n')} ifind={meta.get('ifind')} bars={len(bars)} "
        f"last={bars[-1]['date'] if bars else '-'}"
    )
    return bars, meta


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
        y, m, d = row["date"].split("-")
        week = f"{y}-W{int(d) // 7}"
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
  <text x="{w/2}" y="{h-2}" text-anchor="middle" font-size="10" fill="#999">主力连续 ZL · Path-A TSMOM+ATR</text>
</svg>
'''
    path.write_text(svg, encoding="utf-8")
    return path


def simulate(
    symbols,
    equity0,
    *,
    compound=True,
    risk_pct=1.5,
    l1_mult=1.0,
    max_positions=3,
    max_gross_pct=50.0,
    max_port_risk=8.0,
    max_per_bucket=1,
    min_r20=3.0,
    min_r60=5.0,
    reward_rr=2.0,
    stop_atr_mult=1.0,
    mode="p0",
):
    series = {}
    errors = {}
    sources = {}
    for u in symbols:
        code = u["code"]
        print(f"[bt] fetch {code} {u.get('ticker')} {u['name']}...")
        try:
            hist, meta = fetch_history(u)
            series[code] = {"meta": u, "hist": hist}
            sources[code] = {k: v for k, v in (meta or {}).items() if k != "code"}
            print(
                f"  bars={len(hist)} "
                f"range={hist[0]['date'] if hist else '-'}→{hist[-1]['date'] if hist else '-'}"
            )
        except Exception as e:
            errors[code] = str(e)[:200]
            print(f"  ERR {e}")

    date_hits = Counter()
    for s in series.values():
        for h in s["hist"]:
            date_hits[h["date"]] += 1
    min_cover = max(3, len(series) // 3)
    dates = sorted(d for d, c in date_hits.items() if c >= min_cover)
    if len(dates) < WARMUP + 5:
        dates = sorted(date_hits.keys())[-LOOKBACK_DAYS:]
    if len(dates) < WARMUP + 5:
        return {
            "ok": False,
            "error": "history too short after Sina/Tencent window",
            "errors": errors,
            "bars": {k: len(v["hist"]) for k, v in series.items()},
        }

    idx = {code: {h["date"]: i for i, h in enumerate(s["hist"])} for code, s in series.items()}

    equity = equity0
    gross_equity = equity0
    peak = equity
    gross_peak = equity0
    max_dd = 0.0
    gross_max_dd = 0.0
    cost_total = 0.0
    curve = []
    day_pnls = []
    pos: dict = {}
    trade_exits = {"target": 0, "stop": 0, "signal": 0}
    closed_pnls = []
    block_counts: dict[str, int] = {}

    trade_dates = dates[WARMUP:]
    curves = {}
    if mode != "base":
        curves = load_curves([u["code"] for u in symbols])
    member = {}
    if mode == "member":
        member = load_member_changes(trade_dates, [c for c in series])
    for di, d in enumerate(trade_dates):
        price_pnl = 0.0
        day_cost = 0.0
        prev_d = trade_dates[di - 1] if di > 0 else None

        # 1) manage open positions: stop / target / signal flip
        for code, p in list(pos.items()):
            hist = series[code]["hist"]
            i1 = idx[code].get(d)
            if i1 is None:
                continue
            bar = hist[i1]
            mult = series[code]["meta"]["mult"]
            sign = 1 if p["direction"] == "多" else -1
            reason, px = apply_stop_target(
                p["direction"], p["entry"], p["stop"], p["target"], bar
            )
            # trend flip exit (Path-A conflict / opposite)
            if reason is None:
                r20, r60 = ret_n(hist, i1, 20), ret_n(hist, i1, 60)
                if r20 is not None and r60 is not None:
                    long_ok = r20 > 0 and r60 > 0
                    short_ok = r20 < 0 and r60 < 0
                    if p["direction"] == "多" and not long_ok:
                        reason, px = "signal", bar["close"]
                    elif p["direction"] == "空" and not short_ok:
                        reason, px = "signal", bar["close"]
            if prev_d is not None:
                i0 = idx[code].get(prev_d)
                if i0 is not None:
                    prev_close = hist[i0]["close"]
                    exit_px = px if reason else bar["close"]
                    price_pnl += (exit_px - prev_close) * mult * p["lots"] * sign
            if reason:
                day_cost += fill_cost(series[code]["meta"], px, p["lots"])
                trade_exits[reason] = trade_exits.get(reason, 0) + 1
                risk = abs(p["entry"] - p["stop"]) or 1e-9
                r_mult = ((px - p["entry"]) * sign) / risk
                closed_pnls.append({"date": d, "code": code, "reason": reason, "R": round(r_mult, 2)})
                del pos[code]

        # 2) Path-A entries with ATR stop/target (RR=reward_rr)
        cands = []
        sizing_eq = compound_equity(equity, equity0, compound)
        day_risk = risk_budget_yuan(sizing_eq, risk_pct, l1_mult)
        slots_left = max(0, int(max_positions) - len(pos))
        if slots_left > 0:
            for code, s in series.items():
                if code in pos:
                    continue
                i = idx[code].get(d)
                if i is None or i < WARMUP:
                    continue
                hist = s["hist"]
                r20, r60 = ret_n(hist, i, 20), ret_n(hist, i, 60)
                a = atr14(hist, i)
                if r20 is None or r60 is None or a is None or a <= 0:
                    continue
                if abs(r20) < min_r20 or abs(r60) < min_r60:
                    continue
                if not ((r20 > 0 and r60 > 0) or (r20 < 0 and r60 < 0)):
                    continue
                direction = "多" if r20 > 0 else "空"
                peers = []
                if mode == "climax":
                    bucket = s["meta"].get("bucket")
                    for other, other_s in series.items():
                        if other == code or other_s["meta"].get("bucket") != bucket:
                            continue
                        oi = idx[other].get(d)
                        if oi is None:
                            continue
                        peers.append(ret_n(other_s["hist"], oi, 20))
                blocked = entry_block(
                    mode,
                    hist,
                    i,
                    direction,
                    d,
                    code,
                    a,
                    curves,
                    member,
                    [p for p in peers if p is not None],
                )
                if blocked:
                    block_counts[blocked] = block_counts.get(blocked, 0) + 1
                    continue
                close = hist[i]["close"]
                stop_dist = stop_atr_mult * a
                if direction == "多":
                    stop = close - stop_dist
                    target = close + reward_rr * stop_dist
                else:
                    stop = close + stop_dist
                    target = close - reward_rr * stop_dist
                risk_per_lot = stop_dist * s["meta"]["mult"]
                lots = int(math.floor(day_risk / risk_per_lot)) if risk_per_lot > 0 else 0
                if lots <= 0:
                    continue
                cands.append(
                    {
                        "code": code,
                        "direction": direction,
                        "lots": lots,
                        "close": close,
                        "mult": s["meta"]["mult"],
                        "r20": round(r20, 3),
                        "r60": round(r60, 3),
                        "atr": round(a, 2),
                        "bucket": s["meta"].get("bucket"),
                        "entry": close,
                        "stop": stop,
                        "target": target,
                        "reason": "path_a_rr2",
                    }
                )
            selected, _meta = apply_portfolio_caps(
                cands,
                equity=sizing_eq,
                max_positions=slots_left,
                max_gross_exposure_pct=max_gross_pct,
                max_portfolio_risk_pct=max_port_risk,
                max_per_bucket=max_per_bucket,
                min_r20_pct=min_r20,
                min_r60_pct=min_r60,
            )
            open_buckets = {}
            for p in pos.values():
                b = str(p.get("bucket") or "_")
                open_buckets[b] = open_buckets.get(b, 0) + 1
            for c in selected:
                if int(c.get("lots") or 0) <= 0:
                    continue
                if len(pos) >= int(max_positions):
                    break
                bucket = str(c.get("bucket") or "_")
                if max_per_bucket > 0 and open_buckets.get(bucket, 0) >= int(max_per_bucket):
                    continue
                pos[c["code"]] = {
                    "code": c["code"],
                    "direction": c["direction"],
                    "lots": int(c["lots"]),
                    "entry": float(c["entry"]),
                    "stop": float(c["stop"]),
                    "target": float(c["target"]),
                    "atr": c.get("atr"),
                    "r20": c.get("r20"),
                    "r60": c.get("r60"),
                    "bucket": c.get("bucket"),
                    "reason": c.get("reason"),
                }
                day_cost += fill_cost(series[c["code"]]["meta"], c["entry"], c["lots"])
                open_buckets[bucket] = open_buckets.get(bucket, 0) + 1

        pnl = price_pnl - day_cost
        cost_total += day_cost
        equity += pnl
        gross_equity += price_pnl
        day_pnls.append({"date": d, "pnl": round(pnl, 2), "equity": round(equity, 2)})
        peak = max(peak, equity)
        gross_peak = max(gross_peak, gross_equity)
        dd = (peak - equity) / peak * 100 if peak else 0
        max_dd = max(max_dd, dd)
        gdd = (gross_peak - gross_equity) / gross_peak * 100 if gross_peak else 0
        gross_max_dd = max(gross_max_dd, gdd)

        gross = 0.0
        for c, p in pos.items():
            ii = idx[c].get(d)
            if ii is None:
                continue
            gross += abs(p["lots"]) * series[c]["hist"][ii]["close"] * series[c]["meta"]["mult"]
        curve.append(
            {
                "date": d,
                "equity": round(equity, 2),
                "held": len(pos),
                "pnl": round(pnl, 2),
                "dd_pct": round(dd, 3),
                "gross_pct": round(gross / equity * 100, 2) if equity else 0,
                "codes": sorted(pos.keys()),
            }
        )

    wins_day = sum(1 for x in day_pnls if x["pnl"] > 0)
    n = len(day_pnls)
    ret_pct = (equity / equity0 - 1) * 100
    gross_ret_pct = (gross_equity / equity0 - 1) * 100
    avg_held = (sum(c["held"] for c in curve) / len(curve)) if curve else 0
    closed_n = len(closed_pnls)
    trade_wins = sum(1 for t in closed_pnls if t.get("R", 0) > 0)
    trade_wr = (trade_wins / closed_n * 100) if closed_n else None
    if max_dd >= 20:
        conclusion = "暂停"
    elif max_dd >= 12 or ret_pct <= -5:
        conclusion = "减仓观察"
    else:
        conclusion = "继续L1"

    pool = ",".join(u["code"] for u in symbols)
    return {
        "ok": True,
        "schema_version": "cta-backtest-v9-pathA-cost-filters",
        "batch": BATCH_LABEL,
        "strategy": "path_a_atr_rr2",
        "mode": mode,
        "data_source": "sina+tencent primary, iFinD fallback",
        "curve_coverage": curve_coverage(curves),
        "sources": sources,
        "reward_rr": reward_rr,
        "stop_atr_mult": stop_atr_mult,
        "equity_compound": compound,
        "max_positions": max_positions,
        "max_gross_exposure_pct": max_gross_pct,
        "max_portfolio_risk_pct": max_port_risk,
        "max_per_bucket": max_per_bucket,
        "min_r20_pct": min_r20,
        "min_r60_pct": min_r60,
        "ifind_slot": active_slot(),
        "universe_n": len(symbols),
        "universe": pool,
        "start": trade_dates[0],
        "end": trade_dates[-1],
        "trade_days": n,
        "equity_start": equity0,
        "equity_end": round(equity, 2),
        "gross_equity_end": round(gross_equity, 2),
        "ret_pct": round(ret_pct, 3),
        "gross_ret_pct": round(gross_ret_pct, 3),
        "cost_yuan": round(cost_total, 2),
        "max_dd_pct": round(max_dd, 3),
        "gross_max_dd_pct": round(gross_max_dd, 3),
        "blocks": block_counts,
        "win_rate": round(wins_day / n * 100, 2) if n else None,
        "trade_win_rate": round(trade_wr, 2) if trade_wr is not None else None,
        "closed_trades": closed_n,
        "exits": trade_exits,
        "avg_held": round(avg_held, 2),
        "conclusion": conclusion,
        "errors": errors,
        "bars": {k: len(v["hist"]) for k, v in series.items()},
        "final_positions": pos,
        "equity_curve": curve,
        "equity_curve_weekly": _downsample_weekly(curve),
        "day_pnls_tail": day_pnls[-20:],
        "closed_pnls_tail": closed_pnls[-30:],
        "ifind_calls": usage_report()["count"],
        "summary": (
            f"PathA {mode} {trade_dates[0]}→{trade_dates[-1]} "
            f"净权益 {equity:.0f}（{ret_pct:+.2f}%）毛权益 {gross_equity:.0f}（{gross_ret_pct:+.2f}%）"
            f"成本 {cost_total:.0f}，"
            f"净MaxDD {max_dd:.2f}% 毛MaxDD {gross_max_dd:.2f}%，"
            f"成交{closed_n}笔，结论 {conclusion}"
        ),
    }


def _simulate_cfg(p, mode):
    cfg = p["cfg"]
    print(f"[bt] mode={mode} ifind_so_far={usage_report()['count']}")
    return simulate(
        cfg["symbols"],
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
        mode=mode,
    )


def _row(out: dict) -> dict:
    return {
        "mode": out.get("mode"),
        "net_ret_pct": out.get("ret_pct"),
        "gross_ret_pct": out.get("gross_ret_pct"),
        "max_dd_pct": out.get("max_dd_pct"),
        "gross_max_dd_pct": out.get("gross_max_dd_pct"),
        "cost_yuan": out.get("cost_yuan"),
        "closed_trades": out.get("closed_trades"),
        "trade_win_rate": out.get("trade_win_rate"),
        "blocks": out.get("blocks"),
        "conclusion": out.get("conclusion"),
        "ok": out.get("ok"),
    }


def _choose(rows: list[dict]) -> str:
    """Turn on one P1 filter only when it beats the current 20/60 book on net return and max drawdown.

    The comparison book is `base`: same costs, 20/60 entry, no roll blackout and no P1 filter.
    A filter is adopted only when it beats that book. Otherwise the book stays on base.
    """
    base = next((r for r in rows if r.get("mode") == "base" and r.get("ok")), None)
    if not base:
        return "base"
    best = None
    for row in rows:
        if row.get("mode") not in ("carry", "oi", "member", "climax"):
            continue
        if not row.get("ok"):
            continue
        if row["net_ret_pct"] > base["net_ret_pct"] and row["max_dd_pct"] < base["max_dd_pct"]:
            if best is None or row["net_ret_pct"] > best["net_ret_pct"]:
                best = row
    return best["mode"] if best else "base"


def _write_entry_filter(mode: str) -> None:
    path = ROOT / "universe.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["entry_filter"] = mode
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    import sys

    compare = "--compare" in sys.argv
    p = _load_cfg()
    cfg = p["cfg"]
    print(
        f"[bt] pathA-rr{p['reward_rr']:.0f} equity0={p['equity0']} "
        f"stopATR={p['stop_atr_mult']} compound={p['compound']} n={len(cfg['symbols'])} "
        f"max_pos={p['max_positions']} gross≤{p['max_gross_pct']}% "
        f"atr_risk≤{p['max_port_risk']}% bucket≤{p['max_per_bucket']} "
        f"min_r={p['min_r20']}/{p['min_r60']} ifind={active_slot()} compare={compare}"
    )
    if compare:
        saved = {}
        rows = []
        for mode in ("base", "p0", "carry", "oi", "member", "climax"):
            one = _simulate_cfg(p, mode)
            saved[mode] = one
            rows.append(_row(one))
            print(one.get("summary") or one.get("error"))
        chosen = _choose(rows)
        _write_entry_filter(chosen)
        print(f"[bt] entry_filter={chosen}")
        out = saved[chosen]
        out["comparison"] = rows
        out["entry_filter"] = chosen
    else:
        prior_cmp = None
        try:
            prior_cmp = json.loads((ROOT / "historical_backtest_latest.json").read_text(encoding="utf-8")).get(
                "comparison"
            )
        except Exception:
            prior_cmp = None
        mode = p["entry_filter"] if p["entry_filter"] in ("base", "p0", "carry", "oi", "member", "climax") else "base"
        out = _simulate_cfg(p, mode)
        out["entry_filter"] = mode
        if prior_cmp:
            out["comparison"] = prior_cmp
    rep = usage_report()
    out["ifind_calls"] = rep["count"]
    out["ifind_call_log"] = rep["calls"]
    print(f"[ifind] calls={rep['count']}")
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
            f"PathA ATR RR2 {out.get('start')}→{out.get('end')}",
        )
        print(f"[bt] chart {chart}")
    print(out.get("summary") or out.get("error"))
    print(f"[bt] wrote {path}")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
