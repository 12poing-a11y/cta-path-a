# -*- coding: utf-8 -*-
"""Direction buckets, HMM state, event list, and model scores for the desk.

Daily closes are read from local Sina cache files. Hit rates use those closes
and member files on disk. Carry/basis may soft-call akshare when the local
交割月 cache is thin (see ``basis_data``); failures leave the series empty.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from basis_data import BASIS_EXTREME, basis_extreme_events, carry_gaps_from_akshare
from desk.hmm_regime import fit_hmm
from desk.loaders import format_variety_label, load_json, load_universe, variety_select_labels
from desk.seat_board import (
    EX_ZH,
    GREEN,
    INK,
    RED,
    REGIME_FORMULA,
    _SEAT_POINTS,
    _dir_sign,
    _highlight_code,
    _iso,
    _light,
    _num,
    _snapshot_uncached,
    cached_snapshot,
    exchange_of,
    member_dates,
    regime_bucket_scores,
    universe_rows,
)

WINDOW = 60
MIN_N = 20
SMALL_MOVE = 0.005
MR_BAND = 1.5
CARRY_BAND = 0.002
STATE_COLOR = {"偏多": GREEN, "偏空": RED, "震荡": "#8a8175"}

MODEL_SCORE_FORMULA = (
    "评分 = clip(命中率 + 5 * clip(均收益, -2, 2), 0, 100)。"
    "命中率是 0 到 100 的百分数，分母是窗口里每个有次日收益的交易日。"
    "信号为多或空时，与次日收盘收益同号算命中。"
    "信号为震荡时，只有次日收益刚好为 0 才算命中；"
    "只有「震荡均值回归」额外把 |次日收益|<0.5% 的震荡日算命中。"
    "均收益只平均非平信号日的「方向乘次日收益」，单位是百分数；没有非平信号时记 0。"
    "窗口是最近 60 个已有次日收益的信号日，不足 60 则用全部；少于 20 日则命中率、均收益、评分写样本不足。"
    "综合方向按「评分×模型乘数」加权投票（趋势R2主轴、HMM降权，见 desk/model_vote_weights.json）。两向同权则震荡。"
)
MODEL_RULES = (
    "动量20/60：与路径A开仓门槛相同，r20 与 r60 同号且 |r20|>=3%、|r60|>=5% 时取 r20 的方向，否则震荡。"
    "rN = (close[t]/close[t-N] - 1) * 100，用本地连续合约收盘。"
    "震荡均值回归：|r60|<5% 且 |5日收益|>=1.5% 时与 5 日收益反向；"
    "否则同样在 |r60|<5% 且收盘偏离 20 日均线达到 1.5% 时与偏离反向；其余震荡。"
    "趋势R2：近窗 log(收盘)~时间 OLS，R²达阈则取斜率方向（联合OOS C=R2 主轴；池已排除SC）。"
    "HMM三状态：三状态高斯 HMM，拟合后按均值排序（高=偏多，低=偏空，中=震荡）；投票乘数按A门控OOS降权，不作硬否决。"
    "当天状态是前向滤波的最大概率，不含之后的收益；参数用整段日收益估计。"
    "偏多记多，偏空记空，中间状态记震荡。震荡日不计入这个模型的命中率。"
    "波动突破：ATR14 高于近 60 日 ATR 中位数，或 |r20| 大于 20 日前且 |r20|>=3%。"
    "方向用当日收盘收益的符号。ATR 用 high/low/前收。"
    "席位资金：机构净持仓非零则跟随其符号；否则跟随外资；否则与家人净持仓相反。"
    "三者都是 0 则震荡。净持仓是席位页同一组前 20 多单减空单。"
    "升贴水：优先本地交割月缓存，同一天按到期月排序的近月和次近月；"
    "不够时用 akshare 现货基差（近月→主力价差）或展期收益率补。"
    "gap=(次近-近月)/近月。gap<=-0.2% 记多（贴水），gap>=0.2% 记空（升水），其间震荡。"
    "两边都没有可对齐序列就不列这一行。"
)


def _dir_name(signal: int | None) -> str:
    if signal is None:
        return "样本不足"
    if signal > 0:
        return "多"
    if signal < 0:
        return "空"
    return "震荡"


def _blank_row(name: str, latest: str, n: int) -> dict[str, Any]:
    shown = latest if latest in ("多", "空", "震荡", "无足够日线") else "样本不足"
    return {
        "模型": name,
        "最新方向": shown,
        "命中率": "样本不足",
        "均收益": "样本不足",
        "评分": "样本不足",
        "样本天数": int(n),
    }


def _score_calls(name: str, calls: list[dict], *, chop_hits: bool) -> dict[str, Any]:
    if not calls:
        return _blank_row(name, "样本不足", 0)
    latest = _dir_name(int(calls[-1]["signal"]))
    usable = [row for row in calls if row.get("next_ret") is not None]
    window = usable[-WINDOW:]
    if len(window) < MIN_N:
        return _blank_row(name, latest, len(window))
    hits = 0
    signed: list[float] = []
    for row in window:
        signal = int(row["signal"])
        nxt = float(row["next_ret"])
        if signal == 0:
            if chop_hits and abs(nxt) < SMALL_MOVE:
                hits += 1
            elif nxt == 0:
                hits += 1
        elif nxt != 0 and signal * nxt > 0:
            hits += 1
        if signal != 0 and nxt != 0:
            signed.append(signal * nxt * 100.0)
    hit = hits / len(window) * 100.0
    avg = sum(signed) / len(signed) if signed else 0.0
    score = hit + 5.0 * max(-2.0, min(2.0, avg))
    score = max(0.0, min(100.0, score))
    return {
        "模型": name,
        "最新方向": latest,
        "命中率": round(hit, 1),
        "均收益": round(avg, 3),
        "评分": round(score, 1),
        "样本天数": len(window),
    }


def _sort_models(rows: list[dict]) -> list[dict]:
    def key(row: dict) -> tuple[int, float]:
        score = row.get("评分")
        if isinstance(score, (int, float)):
            return (1, float(score))
        return (0, 0.0)

    return sorted(rows, key=key, reverse=True)


def load_vote_weights(root: Path | None = None) -> dict[str, Any]:
    """Desk model vote multipliers + trend-R2 params (soft defaults if missing)."""
    path = (root or Path(__file__).resolve().parents[1]) / "desk" / "model_vote_weights.json"
    defaults = {
        "multipliers": {
            "趋势R2": 2.0,
            "动量20/60": 1.5,
            "席位资金": 1.2,
            "升贴水": 0.8,
            "波动突破": 0.8,
            "震荡均值回归": 0.5,
            "HMM三状态": 0.25,
        },
        "trend_r2": {"window": 60, "r2_min": 0.2},
    }
    if not path.is_file():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    mult = dict(defaults["multipliers"])
    mult.update({str(k): float(v) for k, v in (raw.get("multipliers") or {}).items()})
    tr = dict(defaults["trend_r2"])
    src = raw.get("trend_r2") or {}
    if isinstance(src, dict):
        if src.get("window") is not None:
            tr["window"] = int(src["window"])
        if src.get("r2_min") is not None:
            tr["r2_min"] = float(src["r2_min"])
    return {"multipliers": mult, "trend_r2": tr, "raw": raw}


def ensemble_of(rows: list[dict], *, root: Path | None = None) -> dict[str, Any]:
    cfg = load_vote_weights(root)
    mults = cfg.get("multipliers") or {}
    weights = {"多": 0.0, "空": 0.0, "震荡": 0.0}
    used = 0
    for row in rows:
        score = row.get("评分")
        direc = row.get("最新方向")
        name = str(row.get("模型") or "")
        if not isinstance(score, (int, float)) or direc not in weights:
            continue
        m = float(mults.get(name, 1.0))
        weights[direc] += float(score) * m
        used += 1
    if used == 0:
        return {
            "direction": "样本不足",
            "weights": weights,
            "text": "综合方向：样本不足",
            "vote_multipliers": mults,
        }
    top = max(weights.values())
    winners = [name for name, value in weights.items() if abs(value - top) < 1e-6]
    choice = winners[0] if len(winners) == 1 else "震荡"
    hmm_m = mults.get("HMM三状态", 1.0)
    r2_m = mults.get("趋势R2", 1.0)
    text = (
        f"综合方向：{choice}（多 {weights['多']:.1f} / 空 {weights['空']:.1f} / "
        f"震荡 {weights['震荡']:.1f}，权重=评分×乘数；R2×{r2_m:g} 主轴 / HMM×{hmm_m:g}）"
    )
    return {
        "direction": choice,
        "weights": weights,
        "text": text,
        "vote_multipliers": mults,
    }


def _trend_r2_calls(
    bars: list[dict], *, window: int = 60, r2_min: float = 0.2
) -> list[dict]:
    """OLS log(close) ~ time; direction = sign(slope) when R² ≥ r2_min else flat."""
    import math

    closes = [float(b["close"]) for b in bars]
    n = len(closes)
    w = max(20, int(window))
    thr = max(0.0, float(r2_min))
    calls: list[dict] = []
    for i in range(n):
        if i + 1 < w:
            calls.append({"date": bars[i]["date"], "signal": 0, "next_ret": None})
            continue
        xs: list[float] = []
        ys: list[float] = []
        ok = True
        for j, idx in enumerate(range(i - w + 1, i + 1)):
            c = closes[idx]
            if c <= 0:
                ok = False
                break
            xs.append(float(j))
            ys.append(math.log(c))
        if not ok or len(xs) < w:
            calls.append({"date": bars[i]["date"], "signal": 0, "next_ret": None})
            continue
        nobs = float(len(xs))
        mx = sum(xs) / nobs
        my = sum(ys) / nobs
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        syy = sum((y - my) ** 2 for y in ys)
        if sxx <= 1e-18 or syy <= 1e-18:
            calls.append({"date": bars[i]["date"], "signal": 0, "next_ret": None})
            continue
        slope = sxy / sxx
        r2 = (sxy * sxy) / (sxx * syy)
        if r2 < thr:
            signal = 0
        elif slope > 0:
            signal = 1
        elif slope < 0:
            signal = -1
        else:
            signal = 0
        calls.append({"date": bars[i]["date"], "signal": signal, "next_ret": None})
    return _attach_next(calls, bars)


def _read_bars(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    by_date: dict[str, dict] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        day = str(row.get("date") or "")[:10]
        close = _num(row.get("close"))
        if not day or close is None or close <= 0:
            continue
        high = _num(row.get("high"))
        low = _num(row.get("low"))
        if high is None:
            high = close
        if low is None:
            low = close
        if high < low:
            high, low = low, high
        by_date[day] = {
            "date": day,
            "close": close,
            "high": high,
            "low": low,
            "volume": _num(row.get("volume")),
            "open_interest": _num(row.get("open_interest")),
        }
    return [by_date[key] for key in sorted(by_date)]


def load_local_bars(root: Path, code: str) -> tuple[list[dict], str]:
    """Best local continuous series. Prefers newest last bar, then length.

    Does not open a network connection — refresh via daily_update / git pull.
    """
    code = str(code or "").upper()
    sina = root / ".cache" / "sina"
    paths: list[Path] = []
    if sina.is_dir():
        paths.extend(sina.glob(f"*/{code}0.json"))
    for folder in (root / "market_data", root / ".cache" / "history", root / ".cache" / "market"):
        candidate = folder / f"{code}0.json"
        if candidate.is_file():
            paths.append(candidate)
    best: list[dict] = []
    source = ""
    best_key = ""
    for path in paths:
        bars = _read_bars(path)
        if not bars:
            continue
        stamp = path.parent.name
        last = str((bars[-1] or {}).get("date") or "")
        # Newest session first; tie-break on length then folder stamp.
        key = f"{last}-{len(bars):08d}-{stamp}"
        if key > best_key:
            best = bars
            best_key = key
            source = f".cache/sina/{stamp}/{path.name}" if "sina" in path.parts else str(path.name)
    return best, source


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _price_calls(
    bars: list[dict],
    *,
    r20_min: float,
    r60_min: float,
) -> tuple[list[dict], list[dict], list[dict]]:
    n = len(bars)
    closes = [bar["close"] for bar in bars]
    dates = [bar["date"] for bar in bars]
    ret1: list[float | None] = [None] * n
    r5: list[float | None] = [None] * n
    r20: list[float | None] = [None] * n
    r60: list[float | None] = [None] * n
    atr: list[float | None] = [None] * n
    for i in range(n):
        if i >= 1 and closes[i - 1] > 0:
            ret1[i] = closes[i] / closes[i - 1] - 1.0
        if i >= 5 and closes[i - 5] > 0:
            r5[i] = (closes[i] / closes[i - 5] - 1.0) * 100.0
        if i >= 20 and closes[i - 20] > 0:
            r20[i] = (closes[i] / closes[i - 20] - 1.0) * 100.0
        if i >= 60 and closes[i - 60] > 0:
            r60[i] = (closes[i] / closes[i - 60] - 1.0) * 100.0
        if i >= 14:
            trs = []
            for j in range(i - 13, i + 1):
                high, low = bars[j]["high"], bars[j]["low"]
                prev = closes[j - 1]
                trs.append(max(high - low, abs(high - prev), abs(low - prev)))
            atr[i] = sum(trs) / 14.0

    def pack(i: int, signal: int) -> dict:
        nxt = ret1[i + 1] if i + 1 < n else None
        return {"date": dates[i], "signal": signal, "next_ret": nxt}

    momentum: list[dict] = []
    revert: list[dict] = []
    breakout: list[dict] = []
    for i in range(n):
        if r20[i] is not None and r60[i] is not None:
            same = (r20[i] > 0 and r60[i] > 0) or (r20[i] < 0 and r60[i] < 0)
            if same and abs(r20[i]) >= r20_min and abs(r60[i]) >= r60_min:
                signal = 1 if r20[i] > 0 else -1
            else:
                signal = 0
            momentum.append(pack(i, signal))
        if r5[i] is not None and r60[i] is not None and i >= 19:
            sma = sum(closes[i - 19 : i + 1]) / 20.0
            dev = (closes[i] / sma - 1.0) * 100.0 if sma else 0.0
            if abs(r60[i]) < r60_min and abs(r5[i]) >= MR_BAND and r5[i] != 0:
                signal = -1 if r5[i] > 0 else 1
            elif abs(r60[i]) < r60_min and abs(dev) >= MR_BAND:
                signal = -1 if dev > 0 else 1
            else:
                signal = 0
            revert.append(pack(i, signal))
        if (
            i >= 40
            and r20[i] is not None
            and r20[i - 20] is not None
            and ret1[i] is not None
        ):
            expanded = abs(r20[i]) > abs(r20[i - 20]) and abs(r20[i]) >= r20_min
            atr_hot = False
            if atr[i] is not None and i >= 73:
                window = [value for value in atr[i - 59 : i + 1] if value is not None]
                if len(window) >= 20 and atr[i] > _median(window):
                    atr_hot = True
            if atr_hot or expanded:
                if ret1[i] > 0:
                    signal = 1
                elif ret1[i] < 0:
                    signal = -1
                else:
                    signal = 0
            else:
                signal = 0
            breakout.append(pack(i, signal))
    return momentum, revert, breakout


def _hmm_view(bars: list[dict]) -> tuple[dict, list[dict]]:
    empty = {
        "ok": False,
        "reason": "无足够日线",
        "backend": "",
        "backend_note": "",
        "latest": "无足够日线",
        "proba": {},
        "means": {},
        "chart": {"dates": [], "returns_pct": [], "states": []},
        "asof": "",
    }
    if len(bars) < 80:
        return empty, []
    closes = [bar["close"] for bar in bars]
    dates = [bar["date"] for bar in bars]
    rets: list[float] = []
    ret_dates: list[str] = []
    for i in range(1, len(closes)):
        if closes[i - 1] <= 0:
            continue
        rets.append(closes[i] / closes[i - 1] - 1.0)
        ret_dates.append(dates[i])
    fitted = fit_hmm(rets)
    if not fitted.get("ok"):
        empty["reason"] = str(fitted.get("reason") or "无足够日线")
        empty["latest"] = "无足够日线"
        empty["backend"] = str(fitted.get("backend") or "")
        empty["backend_note"] = str(fitted.get("backend_note") or "")
        return empty, []
    n = min(len(fitted["signs"]), len(rets), len(ret_dates))
    signs = [int(v) for v in fitted["signs"][:n]]
    labels = [str(v) for v in fitted["labels"][:n]]
    calls = []
    for i, signal in enumerate(signs):
        nxt = rets[i + 1] if i + 1 < n else None
        calls.append({"date": ret_dates[i], "signal": signal, "next_ret": nxt})
    tail = slice(-100, None)
    view = {
        "ok": True,
        "reason": "",
        "backend": fitted.get("backend") or "",
        "backend_note": fitted.get("backend_note") or "",
        "latest": fitted.get("latest") or "震荡",
        "proba": fitted.get("proba") or {},
        "means": fitted.get("means") or {},
        "asof": ret_dates[n - 1] if n else "",
        "chart": {
            "dates": ret_dates[tail],
            "returns_pct": [round(v * 100.0, 3) for v in rets[:n][tail]],
            "states": labels[tail],
        },
    }
    return view, calls


def _exchange_for(root: Path, code: str, report: dict | None) -> str:
    for row in universe_rows(root):
        if row["code"] == code:
            return row["exchange"]
    for sig in (report or {}).get("signals") or []:
        if str(sig.get("code") or "").upper() == code:
            return exchange_of(str(sig.get("ticker") or ""))
    return ""


def _top_net(snap: dict) -> float:
    long_qty = sum(float(row.get("qty") or 0) for row in snap.get("longs") or [])
    short_qty = sum(float(row.get("qty") or 0) for row in snap.get("shorts") or [])
    return long_qty - short_qty


def _seat_signal(snap: dict) -> int:
    inst = float(snap.get("inst_net") or 0)
    foreign = float(snap.get("foreign_net") or 0)
    holder = float(snap.get("holder_net") or 0)
    if inst > 0:
        return 1
    if inst < 0:
        return -1
    if foreign > 0:
        return 1
    if foreign < 0:
        return -1
    if holder > 0:
        return -1
    if holder < 0:
        return 1
    return 0


def seat_series(root: Path, code: str, report: dict | None = None) -> list[dict]:
    code = str(code or "").upper()
    exchange = _exchange_for(root, code, report)
    if exchange not in ("CZCE", "SHFE", "DCE"):
        return []
    # Exchange prints + Eastmoney/Sina underlay (em-*.json) so DCE is not skipped.
    ymds = set(member_dates(root, exchange))
    em_folder = root / ".cache" / "member"
    if em_folder.is_dir():
        for path in em_folder.glob("em-*.json"):
            ymd = path.stem.split("-", 1)[-1]
            if len(ymd) == 8 and ymd.isdigit():
                ymds.add(ymd)
    rows = []
    for ymd in sorted(ymds):
        snap = _snapshot_uncached(root, code, exchange, ymd)
        if not snap.get("ok"):
            continue
        rows.append(
            {
                "date": snap.get("date") or _iso(ymd),
                "signal": _seat_signal(snap),
                "net": _top_net(snap),
            }
        )
    return rows


def _attach_next(rows: list[dict], bars: list[dict]) -> list[dict]:
    index = {bar["date"]: i for i, bar in enumerate(bars)}
    out = []
    for row in rows:
        i = index.get(row["date"])
        nxt = None
        if i is not None and i + 1 < len(bars) and bars[i]["close"] > 0:
            nxt = bars[i + 1]["close"] / bars[i]["close"] - 1.0
        out.append({"date": row["date"], "signal": int(row["signal"]), "next_ret": nxt})
    return out


def _expiry(symbol: str) -> int:
    digits = "".join(ch for ch in symbol if ch.isdigit())
    return int(digits[-4:]) if len(digits) >= 4 else 0


def _bar_alive(bar: dict) -> bool:
    oi = bar.get("open_interest")
    vol = bar.get("volume")
    if oi is not None and vol is not None and oi <= 0 and vol <= 0:
        return False
    return float(bar.get("close") or 0) > 0


def load_carry_gaps(root: Path, code: str) -> list[dict] | None:
    """Front vs next close; Sina delivery months first, akshare basis/roll next."""
    code = str(code or "").upper()
    sina = root / ".cache" / "sina"
    rows: list[dict] = []
    if sina.is_dir():
        pat = re.compile(rf"^{re.escape(code)}\d{{4}}$", re.I)
        best: dict[str, tuple[str, list[dict]]] = {}
        for path in sina.glob(f"*/{code}[0-9][0-9][0-9][0-9].json"):
            if not pat.match(path.stem):
                continue
            bars = _read_bars(path)
            if len(bars) < 5:
                continue
            key = path.stem.upper()
            prev = best.get(key)
            stamp = path.parent.name
            if prev is None or len(bars) > len(prev[1]) or (
                len(bars) == len(prev[1]) and stamp > prev[0]
            ):
                best[key] = (stamp, bars)
        if len(best) >= 2:
            books = {
                sym: {bar["date"]: bar for bar in bars}
                for sym, (_stamp, bars) in best.items()
            }
            dates = sorted({day for book in books.values() for day in book})
            for day in dates:
                alive = []
                for sym, book in books.items():
                    bar = book.get(day)
                    if not bar or not _bar_alive(bar):
                        continue
                    alive.append((_expiry(sym), float(bar["close"])))
                if len(alive) < 2:
                    continue
                alive.sort()
                front, nxt = alive[0][1], alive[1][1]
                if front <= 0:
                    continue
                rows.append({"date": day, "gap": (nxt - front) / front, "source": "sina"})
    if len(rows) >= 10:
        return rows
    ak_rows = carry_gaps_from_akshare(root, code) or []
    if not rows:
        return ak_rows or None
    # Merge: prefer Sina on overlapping days, keep akshare-only days.
    by_day = {r["date"]: r for r in ak_rows}
    by_day.update({r["date"]: r for r in rows})
    merged = [by_day[d] for d in sorted(by_day)]
    return merged or None


def _carry_calls(root: Path, code: str, bars: list[dict]) -> list[dict] | None:
    gaps = load_carry_gaps(root, code)
    if not gaps:
        return None
    calls = []
    for row in gaps:
        gap = float(row["gap"])
        if gap <= -CARRY_BAND:
            signal = 1
        elif gap >= CARRY_BAND:
            signal = -1
        else:
            signal = 0
        calls.append({"date": row["date"], "signal": signal, "next_ret": None})
    return _attach_next(calls, bars)


def build_model_rows(
    root: Path,
    code: str,
    bars: list[dict],
    hmm_calls: list[dict],
    hmm_ok: bool,
    *,
    r20_min: float,
    r60_min: float,
    report: dict | None,
) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    rows: list[dict] = []
    vote_cfg = load_vote_weights(root)
    tr = vote_cfg.get("trend_r2") or {}
    r2_window = int(tr.get("window") or 60)
    r2_min = float(tr.get("r2_min") or 0.2)
    if len(bars) < 80:
        rows.append(_blank_row("趋势R2", "样本不足", len(bars)))
        rows.append(_blank_row("动量20/60", "样本不足", len(bars)))
        rows.append(_blank_row("震荡均值回归", "样本不足", len(bars)))
        rows.append(_blank_row("HMM三状态", "无足够日线", len(bars)))
        rows.append(_blank_row("波动突破", "样本不足", len(bars)))
    else:
        r2_calls = _trend_r2_calls(bars, window=r2_window, r2_min=r2_min)
        momentum, revert, breakout = _price_calls(bars, r20_min=r20_min, r60_min=r60_min)
        rows.append(_score_calls("趋势R2", r2_calls, chop_hits=False))
        rows.append(_score_calls("动量20/60", momentum, chop_hits=False))
        rows.append(_score_calls("震荡均值回归", revert, chop_hits=True))
        if hmm_ok and hmm_calls:
            rows.append(_score_calls("HMM三状态", hmm_calls, chop_hits=False))
        else:
            rows.append(_blank_row("HMM三状态", "无足够日线", 0))
        rows.append(_score_calls("波动突破", breakout, chop_hits=False))

    seats = seat_series(root, code, report)
    if not seats:
        exchange = _exchange_for(root, code, report)
        if exchange == "DCE":
            notes.append("席位资金：本地无 dce/em 会员缓存（东财/新浪应已补），本品种略过。")
        else:
            notes.append("席位资金：本地会员排名里没有这个品种，本品种略过。")
    else:
        rows.append(_score_calls("席位资金", _attach_next(seats, bars), chop_hits=False))

    carry = _carry_calls(root, code, bars)
    if carry is None:
        notes.append("升贴水：本地交割月与 akshare 基差/展期都不够，本品种略过。")
    else:
        rows.append(_score_calls("升贴水", carry, chop_hits=False))
    return _sort_models(rows), notes


def build_symbol_pack(root: Path, code: str) -> dict[str, Any]:
    code = str(code or "").upper()
    report = load_json(root / "l1_report.json")
    uni = load_universe(root) or {}
    r20_min = _num(uni.get("min_r20_pct")) or _num((report or {}).get("min_r20_pct")) or 3.0
    r60_min = _num(uni.get("min_r60_pct")) or _num((report or {}).get("min_r60_pct")) or 5.0
    bars, source = load_local_bars(root, code)
    hmm, hmm_calls = _hmm_view(bars)
    models, notes = build_model_rows(
        root,
        code,
        bars,
        hmm_calls,
        bool(hmm.get("ok")),
        r20_min=float(r20_min),
        r60_min=float(r60_min),
        report=report,
    )
    return {
        "code": code,
        "bars": len(bars),
        "source": source,
        "hmm": hmm,
        "models": models,
        "notes": notes,
        "ensemble": ensemble_of(models, root=root),
        "vote_weights": load_vote_weights(root).get("multipliers"),
    }


def _signal_map(report: dict | None) -> dict[str, dict]:
    out = {}
    for sig in (report or {}).get("signals") or []:
        code = str(sig.get("code") or "").upper()
        if code:
            out[code] = sig
    return out


def _selected_set(report: dict | None) -> set[str] | None:
    port = (report or {}).get("portfolio")
    if not isinstance(port, dict) or "selected" not in port:
        return None
    return {str(code).upper() for code in (port.get("selected") or []) if code}


def _cross_support(prev: float, cur: float, thr: float) -> str:
    if abs(cur) < thr <= abs(prev):
        return "震荡"
    if abs(prev) < thr <= abs(cur):
        if cur > 0:
            return "多"
        if cur < 0:
            return "空"
    return "震荡"


def _load_reports(root: Path, current: dict | None) -> list[dict]:
    found: dict[str, dict] = {}
    archive = root / "archive"
    if archive.is_dir():
        for path in sorted(archive.glob("l1_report_*.json")):
            data = load_json(path)
            if isinstance(data, dict) and data.get("signals"):
                asof = str(data.get("asof") or path.stem.split("_")[-1])
                found[asof] = data
    if current and current.get("signals"):
        found[str(current.get("asof") or "latest")] = current
    return [found[key] for key in sorted(found)]


def report_events(root: Path, current: dict | None) -> list[dict]:
    """Changes between archived l1 reports. Missing fields are not events."""
    reports = _load_reports(root, current)
    events: list[dict] = []
    for older, newer in zip(reports, reports[1:]):
        day = str(newer.get("asof") or "")
        if len(day) == 8 and day.isdigit():
            day = _iso(day)
        old_map = _signal_map(older)
        new_map = _signal_map(newer)
        r20_min = _num(newer.get("min_r20_pct")) or 3.0
        r60_min = _num(newer.get("min_r60_pct")) or 5.0
        for code in sorted(set(old_map) | set(new_map)):
            prev = old_map.get(code)
            cur = new_map.get(code)
            if not prev or not cur:
                continue
            for field, thr in (("r20", r20_min), ("r60", r60_min)):
                if field not in prev or field not in cur:
                    continue
                old_v = _num(prev.get(field))
                new_v = _num(cur.get(field))
                if old_v is None or new_v is None:
                    continue
                if (abs(old_v) < thr) == (abs(new_v) < thr):
                    continue
                events.append(
                    {
                        "日期": day,
                        "代码": code,
                        "类型": "动量跨越",
                        "细节": f"{field} {old_v:+.2f} -> {new_v:+.2f}，穿过 {thr:g}% 门槛",
                        "支持": _cross_support(old_v, new_v, thr),
                        "标记": "事件驱动",
                    }
                )
            if "seat" in prev and "seat" in cur:
                old_seat = str(prev.get("seat") or "").strip() or "无标签"
                new_seat = str(cur.get("seat") or "").strip() or "无标签"
                if old_seat != new_seat:
                    pts = _SEAT_POINTS.get(new_seat, 0.0) * _dir_sign(cur.get("direction"))
                    support = "多" if pts > 0 else "空" if pts < 0 else "震荡"
                    events.append(
                        {
                            "日期": day,
                            "代码": code,
                            "类型": "席位切换",
                            "细节": f"{old_seat} -> {new_seat}",
                            "支持": support,
                            "标记": "",
                        }
                    )
            if "direction" in prev and "direction" in cur:
                old_dir = str(prev.get("direction") or "").strip()
                new_dir = str(cur.get("direction") or "").strip()
                if old_dir and new_dir and old_dir != new_dir:
                    events.append(
                        {
                            "日期": day,
                            "代码": code,
                            "类型": "方向翻转",
                            "细节": f"{old_dir} -> {new_dir}",
                            "支持": {"多": "多", "空": "空"}.get(new_dir, "震荡"),
                            "标记": "",
                        }
                    )
        old_sel = _selected_set(older)
        new_sel = _selected_set(newer)
        if old_sel is None or new_sel is None:
            continue
        for code in sorted(new_sel - old_sel):
            direc = str((new_map.get(code) or {}).get("direction") or "")
            events.append(
                {
                    "日期": day,
                    "代码": code,
                    "类型": "入选变化",
                    "细节": f"进入 portfolio.selected，方向 {direc or '空仓'}",
                    "支持": {"多": "多", "空": "空"}.get(direc, "震荡"),
                    "标记": "",
                }
            )
        for code in sorted(old_sel - new_sel):
            events.append(
                {
                    "日期": day,
                    "代码": code,
                    "类型": "入选变化",
                    "细节": "离开 portfolio.selected",
                    "支持": "震荡",
                    "标记": "",
                }
            )
    return events


def member_flip_events(root: Path, code: str, report: dict | None = None) -> list[dict]:
    code = str(code or "").upper()
    series = seat_series(root, code, report)
    events = []
    prev_net = None
    for row in series:
        net = float(row["net"])
        if prev_net is not None and prev_net * net < 0:
            events.append(
                {
                    "日期": row["date"],
                    "代码": code,
                    "类型": "席位净持仓翻向",
                    "细节": f"前20净持仓 {prev_net:+.0f} -> {net:+.0f}",
                    "支持": "多" if net > 0 else "空",
                    "标记": "事件驱动",
                }
            )
        if net != 0:
            prev_net = net
    return events


def _ymd(value: str) -> str:
    text = str(value or "").replace("-", "").strip()
    return text if len(text) == 8 and text.isdigit() else ""


def _same_sign_mom(
    r20: float | None, r60: float | None, r20_min: float, r60_min: float
) -> str | None:
    """Path-A style same-sign momentum above thresholds → 多/空, else None."""
    if r20 is None or r60 is None:
        return None
    if abs(r20) < r20_min or abs(r60) < r60_min:
        return None
    if (r20 > 0) == (r60 > 0):
        return "多" if r20 > 0 else "空"
    return None


def _mom_cross_dirs(
    prev: dict, cur: dict, r20_min: float, r60_min: float
) -> list[tuple[str, str, float, float, float]]:
    """Return (field, support, old, new, thr) for threshold crosses with 多/空 support."""
    out: list[tuple[str, str, float, float, float]] = []
    for field, thr in (("r20", r20_min), ("r60", r60_min)):
        if field not in prev or field not in cur:
            continue
        old_v = _num(prev.get(field))
        new_v = _num(cur.get(field))
        if old_v is None or new_v is None:
            continue
        if (abs(old_v) < thr) == (abs(new_v) < thr):
            continue
        support = _cross_support(old_v, new_v, thr)
        if support in ("多", "空"):
            out.append((field, support, old_v, new_v, thr))
    return out


def _inst_net_on(root: Path, code: str, exchange: str, ymd: str) -> float | None:
    if exchange not in ("CZCE", "SHFE") or not ymd:
        return None
    snap = _snapshot_uncached(root, code, exchange, ymd)
    if not snap.get("ok"):
        return None
    net = _num(snap.get("inst_net"))
    return float(net) if net is not None else None


def _inst_dir(net: float | None) -> str | None:
    if net is None or net == 0:
        return None
    return "多" if net > 0 else "空"


def joint_skip_reason(root: Path, code: str, report: dict | None = None) -> str | None:
    """Why this symbol cannot form 动量机构同向; None if member files exist."""
    code = str(code or "").upper()
    exchange = _exchange_for(root, code, report)
    if exchange not in ("CZCE", "SHFE", "DCE"):
        return f"{code} 交易所 {exchange or '未知'}，无机构净持仓序列，无法形成「动量机构同向」。"
    if not member_dates(root, exchange):
        if exchange == "DCE":
            return (
                f"{code} 属大商所，本地无 dce-*.json（akshare 缓存），"
                "无法形成「动量机构同向」。"
            )
        return f"{code} 本地 .cache/member 无 {exchange} 文件，无法形成「动量机构同向」。"
    return None


def joint_momentum_institution_events(
    root: Path, current: dict | None, codes: set[str] | None = None
) -> list[dict]:
    """Joint event when momentum direction and institution-group net agree.

    Momentum (event-driven, from archive l1 reports): r20/r60 threshold cross
    into 多/空, or same-sign 20/60 already pointing long/short.
    Institution: net lots of 中信期货/国泰君安/华泰/永安/东证 (inst_net), not OI.
    Emits only when both sides agree and at least one side triggers that day
    (momentum cross / newly same-sign, or institution flip / newly nonzero).
    Standalone 动量跨越 and 席位净持仓翻向 stay separate; this adds 动量机构同向.
    DCE / missing member files are skipped (no fabricated rows).
    """
    reports = _load_reports(root, current)
    if len(reports) < 2:
        return []
    events: list[dict] = []
    want = {str(c).upper() for c in codes} if codes is not None else None

    for older, newer in zip(reports, reports[1:]):
        day_ymd = _ymd(str(newer.get("asof") or ""))
        if not day_ymd:
            continue
        day = _iso(day_ymd)
        prev_ymd = _ymd(str(older.get("asof") or ""))
        r20_min = _num(newer.get("min_r20_pct")) or 3.0
        r60_min = _num(newer.get("min_r60_pct")) or 5.0
        old_map = _signal_map(older)
        new_map = _signal_map(newer)
        for code in sorted(set(old_map) | set(new_map)):
            if want is not None and code not in want:
                continue
            prev = old_map.get(code)
            cur = new_map.get(code)
            if not prev or not cur:
                continue
            exchange = _exchange_for(root, code, newer)
            if exchange not in ("CZCE", "SHFE"):
                continue

            cur_r20 = _num(cur.get("r20"))
            cur_r60 = _num(cur.get("r60"))
            prev_r20 = _num(prev.get("r20"))
            prev_r60 = _num(prev.get("r60"))
            same_now = _same_sign_mom(cur_r20, cur_r60, r20_min, r60_min)
            same_prev = _same_sign_mom(prev_r20, prev_r60, r20_min, r60_min)
            crosses = _mom_cross_dirs(prev, cur, r20_min, r60_min)

            mom_dir: str | None = same_now
            mom_bits: list[str] = []
            mom_trigger = False
            if crosses:
                cross_dirs = {support for _f, support, _o, _n, _t in crosses}
                if len(cross_dirs) == 1:
                    cross_dir = next(iter(cross_dirs))
                    if mom_dir is None:
                        mom_dir = cross_dir
                    if mom_dir == cross_dir:
                        mom_trigger = True
                        for field, support, old_v, new_v, thr in crosses:
                            mom_bits.append(
                                f"{field} {old_v:+.2f}->{new_v:+.2f} 穿{thr:g}%→{support}"
                            )
                elif same_now and same_now in cross_dirs:
                    mom_trigger = True
                    for field, support, old_v, new_v, thr in crosses:
                        if support == same_now:
                            mom_bits.append(
                                f"{field} {old_v:+.2f}->{new_v:+.2f} 穿{thr:g}%→{support}"
                            )
            if same_now:
                if not mom_bits:
                    mom_bits.append(
                        f"20/60同向已指向{same_now}"
                        f"（r20 {cur_r20:+.2f} / r60 {cur_r60:+.2f}，"
                        f"门槛 {r20_min:g}% / {r60_min:g}%）"
                    )
                if same_prev != same_now:
                    mom_trigger = True

            if mom_dir not in ("多", "空"):
                continue

            inst_now = _inst_net_on(root, code, exchange, day_ymd)
            inst_prev = _inst_net_on(root, code, exchange, prev_ymd) if prev_ymd else None
            inst_side = _inst_dir(inst_now)
            if inst_side is None or inst_side != mom_dir:
                continue

            inst_trigger = False
            inst_bits: list[str] = [f"机构净持仓 {inst_now:+.0f} 手→{inst_side}"]
            if inst_prev is None:
                inst_trigger = True
                inst_bits.append("当日首现机构净持仓")
            elif inst_prev == 0 and inst_now != 0:
                inst_trigger = True
                inst_bits.append(f"机构由0变为 {inst_now:+.0f}")
            elif inst_prev * inst_now < 0:
                inst_trigger = True
                inst_bits.append(f"机构翻向 {inst_prev:+.0f}->{inst_now:+.0f}")

            if not (mom_trigger or inst_trigger):
                continue

            events.append(
                {
                    "日期": day,
                    "代码": code,
                    "类型": "动量机构同向",
                    "细节": "；".join(mom_bits + inst_bits),
                    "支持": mom_dir,
                    "标记": "同向",
                }
            )
    return events


def events_for_codes(root: Path, report: dict | None, codes: list[str]) -> list[dict]:
    want = {str(code).upper() for code in codes if code}
    rows = [row for row in report_events(root, report) if row["代码"] in want]
    for row in rows:
        row.setdefault("标记", "")
    for code in sorted(want):
        rows.extend(member_flip_events(root, code, report))
    rows.extend(joint_momentum_institution_events(root, report, want))
    rows.extend(basis_extreme_events(root, want))
    # 动量机构同向 first (badge), then by date; 动量跨越 stays a first-class row.
    joints = [row for row in rows if row.get("类型") == "动量机构同向"]
    others = [row for row in rows if row.get("类型") != "动量机构同向"]
    joints.sort(key=lambda row: (row["日期"], row["代码"]), reverse=True)
    others.sort(key=lambda row: (row["日期"], row["代码"], row["类型"]), reverse=True)
    return joints + others


def _symbol_choices(root: Path, report: dict | None) -> list[dict]:
    rows = list(universe_rows(root))
    known = {row["code"] for row in rows}
    for sig in (report or {}).get("signals") or []:
        code = str(sig.get("code") or "").upper()
        if not code or code in known:
            continue
        rows.append(
            {
                "code": code,
                "name": str(sig.get("name") or code),
                "bucket": str(sig.get("bucket") or ""),
                "exchange": exchange_of(str(sig.get("ticker") or "")),
            }
        )
        known.add(code)
    return rows


def _labels(rows: list[dict], root: Path | None = None) -> list[str]:
    if root is None:
        return [
            f"{row['code']} {row['name']} · {EX_ZH.get(row['exchange'], row['exchange'])}"
            for row in rows
        ]
    return variety_select_labels(root, rows, ex_zh=EX_ZH)


@st.cache_data(show_spinner=False)
def _cached_pack(root_s: str, code: str) -> dict:
    return build_symbol_pack(Path(root_s), code)


@st.cache_data(show_spinner=False)
def _cached_coverage(root_s: str) -> list[tuple[str, int]]:
    root = Path(root_s)
    out = []
    for row in universe_rows(root):
        bars, _source = load_local_bars(root, row["code"])
        out.append((row["code"], len(bars)))
    return out


@st.cache_data(show_spinner=False)
def _cached_events(root_s: str, codes: tuple[str, ...]) -> list[dict]:
    root = Path(root_s)
    report = load_json(root / "l1_report.json")
    return events_for_codes(root, report, list(codes))


def _hmm_figures(chart: dict) -> tuple[go.Figure, go.Figure]:
    dates = chart.get("dates") or []
    rets = chart.get("returns_pct") or []
    states = chart.get("states") or []
    colors = [STATE_COLOR.get(str(state), "#888888") for state in states]
    bars = go.Figure(
        go.Bar(
            x=dates,
            y=rets,
            marker_color=colors,
            customdata=states,
            hovertemplate="%{x}<br>%{y:.2f}%<br>%{customdata}<extra></extra>",
            name="日收益%",
        )
    )
    bars.update_layout(template="plotly_white")
    _light(bars, "近期日收益（颜色是 HMM 状态）", 320, time_axis="recent_right")
    zmap = {"偏多": 1, "震荡": 0, "偏空": -1}
    strip = go.Figure(
        go.Heatmap(
            z=[[zmap.get(str(state), 0) for state in states]],
            x=dates,
            y=["状态"],
            colorscale=[[0.0, RED], [0.5, "#e6e0d6"], [1.0, GREEN]],
            zmin=-1,
            zmax=1,
            showscale=False,
            hovertext=[states],
            hovertemplate="%{x}<br>%{hovertext}<extra></extra>",
        )
    )
    strip.update_layout(template="plotly_white")
    _light(strip, "状态条", 140, time_axis="recent_right")
    return bars, strip


def render_regime_tab(root: Path) -> None:
    st.subheader("状态评分")
    st.caption("浅色底。研究用状态划分，不是交易指令。评分是历史方向命中，不是未来收益承诺。")

    report = load_json(root / "l1_report.json")
    symbols = _symbol_choices(root, report)
    if not symbols:
        st.error("universe.json 没有品种")
        return
    labels = _labels(symbols, root)
    selected_codes = [
        str(sig.get("code") or "").upper()
        for sig in (report or {}).get("signals") or []
        if sig.get("selected")
    ]
    default_code = selected_codes[0] if selected_codes else symbols[0]["code"]
    default_label = next((lab for lab, row in zip(labels, symbols) if row["code"] == default_code), labels[0])
    seat_label = st.session_state.get("seat_sym")
    if "regime_sym" not in st.session_state:
        st.session_state["regime_sym"] = seat_label if seat_label in labels else default_label
    if st.session_state["regime_sym"] not in labels:
        st.session_state["regime_sym"] = default_label

    c_sym, c_btn = st.columns([3, 1])
    with c_sym:
        choice = st.selectbox("品种", labels, key="regime_sym")
    with c_btn:
        st.caption("")
        refresh = st.button("刷新", key="regime_refresh")
    if refresh:
        _cached_pack.clear()
        _cached_events.clear()
        _cached_coverage.clear()
        cached_snapshot.clear()
        try:
            from desk.regime_factor_eval import _cached_regime_factor_assessment

            _cached_regime_factor_assessment.clear()
        except Exception:
            pass
        st.rerun()
    meta = symbols[labels.index(choice)]
    code = meta["code"]
    with st.spinner("读取本地日线并汇总决策..."):
        pack = _cached_pack(str(root), code)
    from desk.decision import render_decision_banner

    from desk.composite_eval import build_full_assessment, render_full_assessment
    from desk.decision import build_decision

    decision = build_decision(root, code, pack=pack, report=report, events=[])
    render_decision_banner(root, code, pack, report)
    st.caption(
        f"品种列表与席位页相同。当前 "
        f"{format_variety_label(code, meta.get('name') or '', root=root, exchange_zh=EX_ZH.get(meta.get('exchange'), meta.get('exchange')))}。"
        "初次打开若席位页已选过品种，沿用那个品种。"
    )

    # Direction buckets needed for full assessment — compute early.
    uni_early = load_universe(root) or {}
    r20_early = _num(uni_early.get("min_r20_pct")) or _num((report or {}).get("min_r20_pct")) or 3.0
    r60_early = _num(uni_early.get("min_r60_pct")) or _num((report or {}).get("min_r60_pct")) or 5.0
    signals_early = (report or {}).get("signals") or []
    regime_row = None
    if signals_early:
        scored_early = regime_bucket_scores(
            signals_early, r20_min=float(r20_early), r60_min=float(r60_early)
        )
        for row in scored_early:
            if str(row.get("代码") or "").upper() == code:
                regime_row = row
                break
    assessment = build_full_assessment(
        root,
        code,
        pack=pack,
        report=report,
        regime_row=regime_row,
        decision=decision,
    )
    render_full_assessment(assessment, expanded=True, root=root)

    from desk.regime_factor_eval import render_regime_factor_panel

    render_regime_factor_panel(root, code)

    st.markdown("**方向评分**")
    st.caption(REGIME_FORMULA)
    uni = load_universe(root) or {}
    r20_min = _num(uni.get("min_r20_pct")) or _num((report or {}).get("min_r20_pct")) or 3.0
    r60_min = _num(uni.get("min_r60_pct")) or _num((report or {}).get("min_r60_pct")) or 5.0
    signals = (report or {}).get("signals") or []
    if not signals:
        st.info("没有 l1_report 信号，方向评分为空。")
        scored_rows: list[dict] = []
    else:
        scored_rows = regime_bucket_scores(signals, r20_min=float(r20_min), r60_min=float(r60_min))
        frame = pd.DataFrame(scored_rows)
        picked = frame.loc[frame["代码"] == code]
        if not picked.empty:
            row = picked.iloc[0]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(f"{code} 多", f"{row['多']:.1f}")
            m2.metric(f"{code} 空", f"{row['空']:.1f}")
            m3.metric(f"{code} 震荡", f"{row['震荡']:.1f}")
            m4.metric("原评分", f"{row['原评分']:+.1f}")
            st.caption(f"{code} 三桶和为 {row['多'] + row['空'] + row['震荡']:.1f}。原评分是席位页的 signed 评分。")
        show_cols = [
            "代码",
            "名称",
            "板块",
            "方向",
            "多",
            "空",
            "震荡",
            "原评分",
            "动量",
            "席位分",
            "入选分",
            "席位",
            "r20",
            "r60",
            "手数",
            "已选",
            "震荡依据",
        ]
        show = frame[[col for col in show_cols if col in frame.columns]]
        sty = show.style.apply(lambda row: _highlight_code(row, code), axis=1).map(
            lambda v: (
                f"color: {GREEN}; font-weight: 600"
                if (_num(v) or 0) > 0
                else f"color: {RED}; font-weight: 600"
                if (_num(v) or 0) < 0
                else ""
            ),
            subset=[col for col in ("原评分", "动量", "席位分", "入选分", "r20", "r60") if col in show.columns],
        ).format(
            {
                key: fmt
                for key, fmt in {
                    "多": "{:.1f}",
                    "空": "{:.1f}",
                    "震荡": "{:.1f}",
                    "原评分": "{:+.1f}",
                    "动量": "{:+.1f}",
                    "席位分": "{:+.1f}",
                    "入选分": "{:+.1f}",
                    "r20": "{:+.2f}",
                    "r60": "{:+.2f}",
                }.items()
                if key in show.columns
            },
            na_rep="—",
        )
        st.dataframe(sty, width="stretch", hide_index=True)
        st.caption(f"{code} 行用浅绿底标出。正数绿色，负数红色。")

    st.markdown("**HMM 行情状态**")
    st.caption("研究用状态划分，不是交易指令。日线只读本地缓存，不访问网络。")
    coverage = _cached_coverage(str(root))
    ready = [name for name, n_bars in coverage if n_bars >= 80]
    short = [name for name, n_bars in coverage if n_bars < 80]
    ready_txt = "、".join(ready) if ready else "无"
    short_txt = "、".join(short) if short else "无"
    st.caption(f"本地连续合约不少于 80 根、可以拟合的品种：{ready_txt}。不足的：{short_txt}。页面只拟合当前品种。")
    hmm = pack.get("hmm") or {}
    if not hmm.get("ok"):
        n_bars = int(pack.get("bars") or 0)
        st.info(f"{code} 无足够日线（本地连续合约收盘 {n_bars} 根，至少需要 80）。")
    else:
        proba = hmm.get("proba") or {}
        means = hmm.get("means") or {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最新状态", str(hmm.get("latest") or "—"))
        c2.metric("偏多概率", f"{float(proba.get('偏多') or 0):.1%}")
        c3.metric("震荡概率", f"{float(proba.get('震荡') or 0):.1%}")
        c4.metric("偏空概率", f"{float(proba.get('偏空') or 0):.1%}")
        backend = str(hmm.get("backend") or "")
        note = str(hmm.get("backend_note") or "")
        extra = f"，{note}" if note and note != backend else ""
        mean_bits = []
        for label in ("偏多", "震荡", "偏空"):
            if label in means:
                mean_bits.append(f"{label} {float(means[label]) * 100:+.3f}%/日")
        st.caption(
            f"状态日 {hmm.get('asof') or '—'} · 后端 {backend}{extra} · "
            f"日线 {pack.get('bars')} 根 · {pack.get('source') or '—'}"
        )
        if mean_bits:
            st.caption("状态均值（日收益）：" + "，".join(mean_bits) + "。")
        bar_fig, strip_fig = _hmm_figures(hmm.get("chart") or {})
        st.plotly_chart(bar_fig, width="stretch")
        st.plotly_chart(strip_fig, width="stretch")

    st.markdown("**事件**")
    st.caption(
        "事件驱动层（研究用，非下单指令）：动量跨越、席位/机构净持仓翻向、动量机构同向、"
        f"基差极端（|主力基差率|≥{BASIS_EXTREME:.0%}，贴水偏多、升水偏空）；"
        "另有方向翻转、席位切换、入选变化。"
        "动量本身是事件驱动的一种，单独成行，不因同向事件被替换或隐藏。"
        "只比较 archive/l1_report_*.json 与当前日报，以及 .cache/member / akshare 基差缓存；不补造。"
        "「动量机构同向」要求动量方向与五家机构净持仓符号一致，且当日至少一侧有触发；排在列表最前并带「同向」标记。"
    )
    scope = st.radio("范围", ["当前品种", "入选组合"], horizontal=True, key="regime_event_scope")
    if scope == "入选组合":
        codes = [
            str(item).upper()
            for item in ((report or {}).get("portfolio") or {}).get("selected") or []
            if item
        ]
        if not codes:
            st.info("当前日报的 portfolio.selected 是空的。")
            codes = []
    else:
        codes = [code]
    for item in codes:
        reason = joint_skip_reason(root, item, report)
        if reason:
            st.caption(reason)
    events: list[dict] = []
    if codes:
        events = _cached_events(str(root), tuple(codes))
    if not events:
        st.info("这个范围里没有对得上的事件。")
    else:
        shown = events[:80]
        frame = pd.DataFrame(shown)
        prefer_cols = ["标记", "日期", "代码", "类型", "细节", "支持"]
        cols = [c for c in prefer_cols if c in frame.columns] + [
            c for c in frame.columns if c not in prefer_cols
        ]
        frame = frame[cols]

        def _event_style(row: pd.Series) -> list[str]:
            if str(row.get("类型") or "") == "动量机构同向":
                return ["background-color: #e8f5e9"] * len(row)
            if str(row.get("类型") or "") == "动量跨越":
                return ["background-color: #fff8e7"] * len(row)
            return [""] * len(row)

        st.dataframe(frame.style.apply(_event_style, axis=1), width="stretch", hide_index=True)
        n_joint = sum(1 for row in events if row.get("类型") == "动量机构同向")
        n_mom = sum(1 for row in events if row.get("类型") == "动量跨越")
        extra = f"同向 {n_joint} · 动量跨越 {n_mom} · "
        if len(events) > 80:
            st.caption(f"{extra}共 {len(events)} 条，表内是最近 80 条。")
        else:
            st.caption(f"{extra}共 {len(events)} 条。")

    st.markdown("**模型评分**")
    st.caption(MODEL_SCORE_FORMULA)
    st.caption(MODEL_RULES)
    st.caption("评分是历史方向命中，不是未来收益承诺。")
    ensemble = pack.get("ensemble") or {}
    e1, e2 = st.columns(2)
    e1.metric("综合方向", str(ensemble.get("direction") or "样本不足"))
    weights = ensemble.get("weights") or {}
    e2.metric(
        "投票权重",
        f"多 {float(weights.get('多') or 0):.0f} / 空 {float(weights.get('空') or 0):.0f} / 震荡 {float(weights.get('震荡') or 0):.0f}",
    )
    for note in pack.get("notes") or []:
        st.caption(note)
    model_rows = pack.get("models") or []
    if model_rows:
        st.dataframe(pd.DataFrame(model_rows), width="stretch", hide_index=True)
    else:
        st.info("没有可显示的模型。")
    st.caption("研究观察，不构成交易建议。")
