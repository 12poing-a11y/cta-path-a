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


Z_OPPORTUNITY = 1.5
DISCLAIMER = "研究观察，不构成交易建议；不下单、不自动开平。"
_FLAG = "★ 潜在机会"


def calendar_side_hint(z: float | None) -> str:
    """跨期方向提示（仅观察）。Z=升贴水(近-次近)相对60日的偏离。"""
    if z is None:
        return "—"
    if z >= Z_OPPORTUNITY:
        return "近贵·观察卖近买远"
    if z <= -Z_OPPORTUNITY:
        return "近便宜·观察买近卖远"
    return "—"


def cross_side_hint(z: float | None, a: str, b: str) -> str:
    """跨品种方向提示：Z 为 A/B 价比偏离。"""
    if z is None:
        return "—"
    if z >= Z_OPPORTUNITY:
        return f"A/B偏高·观察卖{a}买{b}"
    if z <= -Z_OPPORTUNITY:
        return f"A/B偏低·观察买{a}卖{b}"
    return "—"


def is_opportunity(z: float | None) -> bool:
    return z is not None and not pd.isna(z) and abs(float(z)) >= Z_OPPORTUNITY


def rank_by_abs_z(df: pd.DataFrame, z_col: str = "Z(60)") -> pd.DataFrame:
    """Sort by |Z| descending (missing Z last); add |Z| and 潜在机会 columns."""
    if df.empty or z_col not in df.columns:
        return df
    out = df.copy()
    z = pd.to_numeric(out[z_col], errors="coerce")
    out["|Z|"] = z.abs().round(2)
    out["潜在机会"] = [_FLAG if is_opportunity(v) else "" for v in z]
    out["_k"] = z.abs()
    out = out.sort_values("_k", ascending=False, na_position="last", kind="stable")
    return out.drop(columns="_k").reset_index(drop=True)


def top_opportunities(cal: pd.DataFrame, cross: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Hottest calendar + cross rows (|Z|>=threshold), merged and ranked by |Z|."""
    cols = ["类型", "标的", "Z(60)", "|Z|", "方向提示"]
    parts = []
    if not cal.empty and "Z(60)" in cal.columns:
        c = cal.copy()
        c["类型"], c["标的"] = "跨期", c["品种"]
        parts.append(c[["类型", "标的", "Z(60)", "方向提示"]])
    if not cross.empty and "Z(60)" in cross.columns:
        x = cross.copy()
        x["类型"], x["标的"] = "跨品种", x["配对"]
        parts.append(x[["类型", "标的", "Z(60)", "方向提示"]])
    if not parts:
        return pd.DataFrame(columns=cols)
    allr = pd.concat(parts, ignore_index=True)
    z = pd.to_numeric(allr["Z(60)"], errors="coerce")
    allr = allr[z.abs() >= Z_OPPORTUNITY].copy()
    if allr.empty:
        return pd.DataFrame(columns=cols)
    allr["|Z|"] = pd.to_numeric(allr["Z(60)"], errors="coerce").abs().round(2)
    allr = allr.sort_values("|Z|", ascending=False, kind="stable").head(n)
    return allr[cols].reset_index(drop=True)


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
                    "方向提示": "—",
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
                "方向提示": calendar_side_hint(z),
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
                    "方向提示": "—",
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
                "方向提示": cross_side_hint(z, a, b),
                "样本日": len(ratio),
            }
        )
    return pd.DataFrame(rows)


def render_arb_panel(root: Path) -> None:
    st.subheader("跨期 / 跨品种套利观察")
    st.caption(
        "研究用：跨期=近月相对次近月升贴水及 60 日 Z；跨品种=同板块价比(A/B) Z。"
        f"按 |Z| 降序排列，|Z|≥{Z_OPPORTUNITY} 标「潜在机会」并给方向提示。{DISCLAIMER}"
    )
    uni = load_universe(root) or {}
    codes = [
        str(s.get("code") or "").upper()
        for s in (uni.get("symbols") or [])
        if isinstance(s, dict) and s.get("code")
    ]
    with st.spinner("计算近次月升贴水…"):
        cdf = rank_by_abs_z(calendar_arb_rows(root, codes))
    xdf = rank_by_abs_z(cross_arb_rows(root))

    top = top_opportunities(cdf, xdf)
    with st.expander(f"最热机会 Top（|Z|≥{Z_OPPORTUNITY}）· {len(top)} 条", expanded=True):
        if top.empty:
            st.info("暂无 |Z| 达到阈值的跨期/跨品种偏离。")
        else:
            st.dataframe(top, use_container_width=True, hide_index=True)
        st.caption(DISCLAIMER)

    t1, t2 = st.tabs(["跨期（近远月）", "跨品种价比"])
    with t1:
        if cdf.empty:
            st.info("无品种可算。")
        else:
            st.dataframe(cdf, use_container_width=True, hide_index=True)
            hot = int((cdf["潜在机会"] == _FLAG).sum()) if "潜在机会" in cdf.columns else 0
            st.caption(f"潜在机会 {hot} / {len(cdf)} · 来源优先本地交割月，不足再 akshare。")
    with t2:
        if xdf.empty:
            st.info("宇宙内固定配对暂无足够重叠日线。")
        else:
            st.dataframe(xdf, use_container_width=True, hide_index=True)
            st.caption("配对为流动性观察集，非完整套利宇宙。Z 为 A/B 价比偏离。")