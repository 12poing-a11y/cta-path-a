# -*- coding: utf-8 -*-
"""Last-bar captions for the research chart tab.

Kept separate from ``desk.chart_board`` so unit tests can import these helpers
without Plotly or Streamlit. The desk still renders charts with Plotly.
"""
from __future__ import annotations

import pandas as pd


def last_bar_timestamp(bars: list[dict] | None) -> str:
    """Newest bar clock. Prefer ``datetime``; fall back to the calendar ``date``."""
    return max(
        (str(row.get("datetime") or row.get("date") or "") for row in (bars or [])),
        default="",
    )


def format_last_daily_bar_caption(daily: pd.DataFrame) -> str:
    """Daily/weekly/monthly caption: last cached bar, plus a reminder to sync."""
    last = str(daily["date"].iloc[-1]) if not daily.empty else "—"
    return (
        f"本地图表数据最后一根K线：{last} · 数据文件来自本地缓存；"
        "先在侧边栏「同步日报」同步 main 行情缓存。"
    )
