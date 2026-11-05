# -*- coding: utf-8 -*-
"""Gamma Wall dashboard panel (daily snapshots; read-only)."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from gamma_wall import fetch_snapshot, load_history, migration_rows


def render_gamma_panel(root: Path) -> None:
    st.subheader("期权 Gamma Wall · 正负对称结构")
    st.caption("免费数据源：郑商所期权日行情 + 新浪目标期货合约日线；只读研究，不下单。")
    c1, c2, c3 = st.columns([1, 1, 1])
    contract = c1.selectbox("目标合约", ["CF2701", "SR2701"], index=0)
    window = c2.selectbox("墙位迁移窗口（交易日）", [5, 10, 20, 30, 60], index=2)
    expiry = c3.text_input("期权到期/最后交易日", value="", placeholder="YYYY-MM-DD")
    st.caption("到期日需按郑商所对应期权合约规则核实后填写；系统不猜日期。")
    if st.button("拉取并计算当日 Gamma 快照", type="primary"):
        if len(expiry) != 10:
            st.error("请先填写经核实的到期/最后交易日 YYYY-MM-DD。")
        else:
            try:
                with st.spinner("调用免费期权日行情与目标期货合约日线…"):
                    snap = fetch_snapshot(contract, expiry=expiry, root=root)
                st.success(f"快照完成：{snap['asof']} · {snap['data_quality']['valid_strikes']} 个有效行权价")
                st.rerun()
            except Exception as exc:
                st.error(f"计算失败：{exc}")
    history = load_history(contract, root=root)
    if not history:
        st.info("尚无历史快照。首次运行后开始累积墙位迁移历史；不使用虚构数据回填。")
        return
    latest = history[-1]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Call Wall", f"{latest['call_wall']:,.0f}")
    m2.metric("Put Wall", f"{latest['put_wall']:,.0f}")
    m3.metric("目标期货结算/收盘", f"{latest['futures_price']:,.0f}")
    m4.metric("有效行权价", latest["data_quality"]["valid_strikes"])
    st.caption(f"数据日期 {latest['asof']} · 期权系列 {latest['option_month']} · 到期日 {latest['expiry']} · {latest['source']}")
    df = pd.DataFrame(latest["rows"])
    fig = go.Figure()
    fig.add_bar(x=df["strike"], y=df["call_gex"], name="Call 侧 Gamma 集中", marker_color="#16a36a")
    fig.add_bar(x=df["strike"], y=df["put_gex"], name="Put 侧 Gamma 集中", marker_color="#d84b5b")
    fig.add_hline(y=0, line_color="#777", line_width=1)
    fig.add_vline(x=latest["futures_price"], line_dash="dash", line_color="#3980d8",
                  annotation_text="期货现价/结算价")
    fig.add_vline(x=latest["call_wall"], line_dash="dot", line_color="#16a36a",
                  annotation_text=f"Call Wall {latest['call_wall']:g}")
    fig.add_vline(x=latest["put_wall"], line_dash="dot", line_color="#d84b5b",
                  annotation_text=f"Put Wall {latest['put_wall']:g}")
    fig.update_layout(title="Call / Put Gamma 集中度（零轴对称展示，不代表 Dealer 净方向）",
        xaxis_title="行权价", yaxis_title="近似 1% 标的价格变动对应 Gamma 暴露",
        barmode="relative", hovermode="x unified", legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True)
    st.warning(latest["disclaimer"])
    hist = migration_rows(contract, window=window, root=root)
    if hist:
        hdf = pd.DataFrame(hist)
        st.subheader(f"墙位迁移 · 最近 {window} 个交易日")
        mf = go.Figure()
        mf.add_trace(go.Scatter(x=hdf["date"], y=hdf["call_wall"], mode="lines+markers", name="Call Wall"))
        mf.add_trace(go.Scatter(x=hdf["date"], y=hdf["put_wall"], mode="lines+markers", name="Put Wall"))
        mf.add_trace(go.Scatter(x=hdf["date"], y=hdf["futures_price"], mode="lines+markers", name="期货价格"))
        mf.update_layout(xaxis_title="交易日", yaxis_title="价格/行权价", hovermode="x unified")
        st.plotly_chart(mf, use_container_width=True)
        st.dataframe(hdf.sort_values("date", ascending=False), use_container_width=True, hide_index=True)
        st.caption(f"当前可用历史 {len(history)} 个交易日；窗口 {window} 日。历史不足不会补造数据。")
