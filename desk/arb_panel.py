# -*- coding: utf-8 -*-
"""Calendar (front-next) and cross-variety spread observation — research only."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from desk.loaders import format_variety_label, load_universe
from desk.regime_board import load_carry_gaps, load_local_bars

# Liquid observation pairs within Path-A universe buckets.
CROSS_PAIRS = (
    ("RB", "I", "黑色"),
    ("RB", "JM", "黑色"),
    ("I", "JM", "黑色"),
    ("MA", "TA", "能化"),
    ("MA", "EG", "能化"),
    ("FG", "SA", "能化"),
    ("M", "P", "农产品"),
    ("CU", "AL", "有色"),
    ("AU", "AG", "贵金属"),
)


def _zscore(series: pd.Series, window: int = 60) -> float | None:
    s = series.dropna()
    if len(s) < max(20, window // 2):
        return None
    w = s.tail(window)
    mu, sd = float(w.mean()), float(w.std(ddof=0))
    if sd <= 1e-12:
        return 0.0
    return (float(w.iloc[-1]) - mu) / sd


def _signal_from_z(z: float | None) -> str:
    if z is None:
        return "样本不足"
    if z >= 1.5:
        return "价差偏高·观察回归"
    if z <= -1.5:
        return "价差偏低·观察回归"
    if abs(z) < 0.5:
        return "中性"
    return "温和偏离"


def calendar_arb_rows(root: Path, codes: list[str]) -> pd.DataFrame:
    rows = []
    for code in codes:
        gaps = load_carry_gaps(root, code)
        if not gaps or len(gaps) < 10:
            rows.append(
                {
                    "品种": format_variety_label(code, "", root=root),
                    "近次月升贴水%": None,
                    "Z(60)": None,
                    "观察": "缺近远月",
                    "样本日": 0,
                    "来源": "—",
                }
            )
            continue
        s = pd.Series({str(g["date"])[:10]: float(g["gap"]) for g in gaps}).sort_index()
        last = float(s.iloc[-1])
        z = _zscore(s)
        src = str((gaps[-1] or {}).get("source") or "—")
        rows.append(
            {
                "品种": format_variety_label(code, "", root=root),
                "近次月升贴水%": round(last * 100, 3),
                "Z(60)": None if z is None else round(z, 2),
                "观察": _signal_from_z(z),
                "样本日": len(s),
                "来源": src,
            }
        )
    return pd.DataFrame(rows)


def _close_map(bars: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for b in bars:
        d = str(b.get("date") or "")[:10]
        try:
            c = float(b.get("close"))
        except (TypeError, ValueError):
            continue
        if len(d) == 10 and c > 0:
            out[d] = c
    return out


def cross_arb_rows(root: Path) -> pd.DataFrame:
    uni = load_universe(root) or {}
    have = {
        str(s.get("code") or "").upper()
        for s in (uni.get("symbols") or [])
        if isinstance(s, dict)
    }
    rows = []
    cache: dict[str, dict[str, float]] = {}
    for a, b, bucket in CROSS_PAIRS:
        if a not in have or b not in have:
            continue
        for code in (a, b):
            if code not in cache:
                bars, _ = load_local_bars(root, code)
                cache[code] = _close_map(bars or [])
        ma, mb = cache[a], cache[b]
        common = sorted(set(ma) & set(mb))
        if len(common) < 30:
            rows.append(
                {
                    "板块": bucket,
                    "配对": f"{a}/{b}",
                    "价比": None,
                    "Z(60)": None,
                    "观察": "样本不足",
                    "样本日": len(common),
                }
            )
            continue
        ratio = pd.Series({d: ma[d] / mb[d] for d in common if mb[d] > 0}).sort_index()
        last = float(ratio.iloc[-1])
        z = _zscore(ratio)
        rows.append(
            {
                "板块": bucket,
                "配对": f"{a}/{b}",
                "价比": round(last, 4),
                "Z(60)": None if z is None else round(z, 2),
                "观察": _signal_from_z(z),
                "样本日": len(ratio),
            }
        )
    return pd.DataFrame(rows)


def render_arb_panel(root: Path) -> None:
    st.subheader("跨期 / 跨品种套利观察")
    st.caption(
        "研究用：跨期=近月相对次近月升贴水及 60 日 Z；跨品种=同板块价比 Z。"
        "|Z|≥1.5 标「观察回归」。不下单、不自动开平。"
    )
    uni = load_universe(root) or {}
    codes = [
        str(s.get("code") or "").upper()
        for s in (uni.get("symbols") or [])
        if isinstance(s, dict) and s.get("code")
    ]
    t1, t2 = st.tabs(["跨期（近远月）", "跨品种价比"])
    with t1:
        with st.spinner("计算近次月升贴水…"):
            cdf = calendar_arb_rows(root, codes)
        if cdf.empty:
            st.info("无品种可算。")
        else:
            st.dataframe(cdf, use_container_width=True, hide_index=True)
            hot = cdf[cdf["观察"].astype(str).str.contains("回归", na=False)]
            st.caption(f"极端偏离 {len(hot)} / {len(cdf)} · 来源优先本地交割月，不足再 akshare。")
    with t2:
        xdf = cross_arb_rows(root)
        if xdf.empty:
            st.info("宇宙内固定配对暂无足够重叠日线。")
        else:
            st.dataframe(xdf, use_container_width=True, hide_index=True)
            st.caption("配对为流动性观察集，非完整套利宇宙。")
