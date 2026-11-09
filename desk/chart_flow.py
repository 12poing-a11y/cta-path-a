# -*- coding: utf-8 -*-
"""Volume-profile (chip-like) and seat capital-flow panels for the chart page."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from desk.regime_board import load_local_bars
from desk.seat_board import load_group_frame, universe_rows


VP_LOOKBACKS = [20, 40, 60, 120, 250]
VP_DEFAULT_LOOKBACK = 60
SEAT_CAPTION = (
    "席位口径：「机构」= 前20名中信期货/国泰君安/华泰/永安/东证(融汇)的净持仓合计；"
    "不是散户/家人（散户代理为东方财富/平安/方正中期/徽商/中信建投，见 member_rank._HOLDER）。"
)


def vp_title(lookback: int, n_bars: int) -> str:
    used = min(lookback, n_bars) if n_bars else lookback
    if n_bars and n_bars < lookback:
        return f"近{lookback}日成交量分布（价轴·实际仅{used}日）"
    return f"近{lookback}日成交量分布（价轴）"


def volume_profile(bars: list[dict], *, bins: int = 24, lookback: int = 60) -> pd.DataFrame:
    """Approximate volume-at-price from daily typical price × volume."""
    if not bars:
        return pd.DataFrame(columns=["price", "volume"])
    use = bars[-lookback:] if lookback and len(bars) > lookback else bars
    rows = []
    for b in use:
        try:
            h, l, c = float(b["high"]), float(b["low"]), float(b["close"])
            v = float(b.get("volume") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if v <= 0 or l <= 0 or h < l:
            continue
        mid = (h + l + c) / 3.0
        rows.append((mid, v))
    if not rows:
        return pd.DataFrame(columns=["price", "volume"])
    df = pd.DataFrame(rows, columns=["price", "volume"])
    lo, hi = float(df["price"].min()), float(df["price"].max())
    if hi <= lo:
        return pd.DataFrame([{"price": lo, "volume": float(df["volume"].sum())}])
    cats = pd.cut(df["price"], bins=bins, include_lowest=True)
    grp = df.groupby(cats, observed=False)["volume"].sum().reset_index()
    grp["price"] = grp["price"].apply(lambda x: float(x.mid) if hasattr(x, "mid") else None)
    return grp.dropna(subset=["price"])[["price", "volume"]].sort_values("price")


def seat_flow_frame(root: Path, code: str, *, window: int = 15) -> pd.DataFrame:
    """Institution net-position series as capital-flow proxy."""
    meta = next((r for r in universe_rows(root) if r.get("code") == code), None)
    if not meta:
        return pd.DataFrame()
    exchange = str(meta.get("exchange") or "")
    end = ""
    # Prefer latest local bar date as end.
    bars, _ = load_local_bars(root, code)
    if bars:
        end = str(bars[-1].get("date") or "")[:10].replace("-", "")
    if len(end) != 8:
        from market_data import latest_expected_session_date

        end = latest_expected_session_date().strftime("%Y%m%d")
    try:
        frame = load_group_frame(root, code, exchange, end, max(window + 5, 20))
    except Exception:
        return pd.DataFrame()
    if frame.empty or "inst_net" not in frame.columns:
        return pd.DataFrame()
    df = frame[["date", "inst_net"]].dropna().copy()
    df["date"] = df["date"].astype(str).str[:10]
    df["net"] = pd.to_numeric(df["inst_net"], errors="coerce")
    df = df.dropna(subset=["net"]).drop_duplicates("date").sort_values("date")
    df["chg"] = df["net"].diff()
    return df.tail(window)


def render_chart_flow_section(root: Path, code: str) -> None:
    st.markdown("**筹码分布（量价近似）与资金流向（席位）**")
    st.caption(
        "期货无标准股票筹码峰：用近窗日线典型价×成交量做 VP 直方图；"
        "资金流向用机构席位净持仓变动近似，非股票主力资金口径。"
    )
    st.caption(SEAT_CAPTION)
    lookback = st.selectbox(
        "VP 回看窗口（交易日）",
        VP_LOOKBACKS,
        index=VP_LOOKBACKS.index(VP_DEFAULT_LOOKBACK),
        key=f"vp_lookback_{code}",
    )
    bars, src = load_local_bars(root, code)
    c1, c2 = st.columns(2)
    with c1:
        vp = volume_profile(bars or [], lookback=int(lookback))
        if vp.empty:
            st.info(f"量价分布不足（源 {src or '无'}）")
        else:
            fig = go.Figure(
                go.Bar(
                    x=vp["volume"],
                    y=vp["price"],
                    orientation="h",
                    marker_color="#64748b",
                    name="量",
                )
            )
            if bars:
                try:
                    last = float(bars[-1]["close"])
                    fig.add_hline(
                        y=last, line_dash="dot", line_color="#2563eb", annotation_text="最新价"
                    )
                except (KeyError, TypeError, ValueError):
                    pass
            fig.update_layout(
                height=360,
                margin=dict(t=24, b=24, l=48, r=16),
                title=vp_title(int(lookback), len(bars or [])),
                xaxis_title="成交量",
                yaxis_title="价格",
            )
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        flow = seat_flow_frame(root, code)
        if flow.empty:
            st.info("本地席位净持仓序列不足，无法画资金流向。")
        else:
            fig = go.Figure()
            fig.add_bar(x=flow["date"], y=flow["chg"], name="净持仓日变化")
            fig.add_scatter(
                x=flow["date"],
                y=flow["net"],
                name="净持仓",
                mode="lines+markers",
                yaxis="y2",
            )
            fig.update_layout(
                height=360,
                margin=dict(t=24, b=24, l=48, r=48),
                title="机构席位净持仓变动",
                yaxis=dict(title="日变化"),
                yaxis2=dict(title="净持仓", overlaying="y", side="right"),
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig, use_container_width=True)
            last_chg = flow["chg"].iloc[-1]
            if pd.isna(last_chg):
                st.caption("最近一日变化：—")
            else:
                st.caption(
                    f"最近一日净持仓变化 {float(last_chg):+.0f} · "
                    f"{'流入偏多' if last_chg > 0 else ('流出偏空' if last_chg < 0 else '持平')}"
                )
