# -*- coding: utf-8 -*-
"""Plotly chart helpers for the Streamlit research desk."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from desk.loaders import drawdown_from_equity


def equity_overlay_fig(
    aligned: pd.DataFrame,
    *,
    title: str = "净值对比",
    y_title: str = "权益",
) -> go.Figure:
    fig = go.Figure()
    if aligned is None or aligned.empty:
        fig.update_layout(title=title, annotations=[dict(text="暂无曲线数据", showarrow=False)])
        return fig
    for col in aligned.columns:
        fig.add_trace(
            go.Scatter(
                x=aligned.index,
                y=aligned[col],
                mode="lines",
                name=str(col),
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title=y_title,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=40, r=20, t=60, b=40),
        hovermode="x unified",
    )
    return fig


def drawdown_overlay_fig(
    aligned: pd.DataFrame,
    *,
    title: str = "回撤 (%)",
) -> go.Figure:
    fig = go.Figure()
    if aligned is None or aligned.empty:
        fig.update_layout(title=title, annotations=[dict(text="暂无回撤数据", showarrow=False)])
        return fig
    for col in aligned.columns:
        dd = drawdown_from_equity(aligned[col].dropna())
        fig.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd,
                mode="lines",
                name=str(col),
                fill="tozeroy",
            )
        )
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="回撤 %",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=40, r=20, t=60, b=40),
        hovermode="x unified",
    )
    return fig


def sleeve_bar_fig(sleeve_df: pd.DataFrame, *, title: str = "对照 sleeve 累计 PnL") -> go.Figure:
    if sleeve_df is None or sleeve_df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[dict(text="无 sleeve 数据", showarrow=False)])
        return fig
    if "sleeve" in sleeve_df.columns and "pnl" in sleeve_df.columns and "date" not in sleeve_df.columns:
        fig = px.bar(sleeve_df, x="sleeve", y="pnl", title=title, text_auto=".2s")
        fig.update_layout(margin=dict(l=40, r=20, t=60, b=40))
        return fig
    # time series of cumulative sleeve columns
    value_cols = [c for c in sleeve_df.columns if c != "date"]
    melted = sleeve_df.melt(id_vars=["date"], value_vars=value_cols, var_name="sleeve", value_name="pnl")
    fig = px.line(melted, x="date", y="pnl", color="sleeve", title=title)
    fig.update_layout(margin=dict(l=40, r=20, t=60, b=40), hovermode="x unified")
    return fig


def kpi_table(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
