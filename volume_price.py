# -*- coding: utf-8 -*-
"""Intraday volume-price heuristics from 15m / 60m bars (research only)."""
from __future__ import annotations

from typing import Any

import pandas as pd


def analyze_volume_price(
    bars: list[dict],
    *,
    period: str = "15",
    lookback: int = 20,
    path_a_direction: str | None = None,
) -> dict[str, Any]:
    """Label recent volume-price structure; soft empty when bars are short."""
    if not bars:
        return {"ok": False, "label": "无分钟数据", "note": "缺少 15m/60m 量能", "period": period}
    df = pd.DataFrame(bars).sort_values("datetime").reset_index(drop=True)
    if len(df) < 5:
        return {"ok": False, "label": "样本不足", "note": f"仅 {len(df)} 根", "period": period}

    window = df.tail(max(lookback, 8)).copy()
    window["vol_ma"] = window["volume"].rolling(min(lookback, len(window)), min_periods=3).mean()
    last = window.iloc[-1]
    prev = window.iloc[-2]
    vol = float(last["volume"] or 0)
    vol_ma = float(last["vol_ma"] or 0) or 1.0
    vol_ratio = vol / vol_ma
    px_chg = float(last["close"]) - float(last["open"])
    px_pct = px_chg / float(last["open"]) if float(last["open"]) else 0.0
    ret_vs_prev = float(last["close"]) / float(prev["close"]) - 1.0 if float(prev["close"]) else 0.0

    # Session volume pace vs prior sessions (same period bars).
    df["date"] = df["date"].astype(str).str[:10]
    by_day = df.groupby("date", sort=True)["volume"].sum()
    session_note = ""
    session_ratio = None
    if len(by_day) >= 2:
        today = by_day.index[-1]
        today_vol = float(by_day.iloc[-1])
        prior = by_day.iloc[:-1].tail(5)
        prior_mean = float(prior.mean()) if len(prior) else 0.0
        if prior_mean > 0:
            session_ratio = today_vol / prior_mean
            session_note = f"当日累计量/近5日均量={session_ratio:.2f}（{today}）"

    if abs(px_pct) < 0.0008 and vol_ratio >= 1.5:
        label = "放量滞涨/滞跌"
        stance = "分歧"
    elif px_pct > 0.0008 and vol_ratio >= 1.5:
        label = "放量上攻"
        stance = "偏多"
    elif px_pct < -0.0008 and vol_ratio >= 1.5:
        label = "放量下跌"
        stance = "偏空"
    elif px_pct > 0.0008 and vol_ratio <= 0.7:
        label = "缩量上涨"
        stance = "谨慎偏多"
    elif px_pct < -0.0008 and vol_ratio <= 0.7:
        label = "缩量下跌"
        stance = "谨慎偏空"
    elif vol_ratio >= 1.3:
        label = "放量震荡"
        stance = "观望"
    else:
        label = "量能平稳"
        stance = "中性"

    # Simple divergence: price higher high vs prior high but volume lower.
    diverge = ""
    if len(window) >= 10:
        hi_idx = int(window["high"].values.argmax())
        if hi_idx == len(window) - 1:
            earlier = window.iloc[:-1]
            if float(last["high"]) >= float(earlier["high"].max()) and vol < float(earlier["volume"].tail(5).mean()):
                diverge = "价新高量未跟随"
                if "上攻" in label:
                    label = "冲高量能背离"
                    stance = "谨慎"

    path_note = ""
    align = None
    direction = str(path_a_direction or "")
    if direction in ("多", "空"):
        if direction == "多" and stance in ("偏多", "谨慎偏多"):
            align = "共振"
        elif direction == "空" and stance in ("偏空", "谨慎偏空"):
            align = "共振"
        elif direction == "多" and stance in ("偏空", "谨慎偏空"):
            align = "冲突"
        elif direction == "空" and stance in ("偏多", "谨慎偏多"):
            align = "冲突"
        else:
            align = "中性"
        path_note = f"PathA={direction} · 量价={align}"

    judgment = f"{period}m · {label} · {stance}"
    if align:
        judgment += f" · 与PathA{align}"

    return {
        "ok": True,
        "period": period,
        "label": label,
        "stance": stance,
        "align": align,
        "judgment": judgment,
        "vol_ratio": round(vol_ratio, 2),
        "px_pct": round(px_pct * 100, 3),
        "ret_vs_prev_pct": round(ret_vs_prev * 100, 3),
        "last_volume": vol,
        "vol_ma": round(vol_ma, 1),
        "last_datetime": str(last.get("datetime")),
        "session_ratio": None if session_ratio is None else round(session_ratio, 2),
        "session_note": session_note,
        "diverge": diverge,
        "path_note": path_note,
        "note": "；".join(x for x in (session_note, diverge, path_note) if x) or "研究观察，不下单",
    }
