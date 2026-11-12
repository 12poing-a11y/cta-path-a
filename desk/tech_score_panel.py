# -*- coding: utf-8 -*-
"""Technical analysis scoreboard UI (build logic in desk/tech_score.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from desk.tech_score import (  # noqa: F401  (re-exported for backward compat)
    OUT_REL,
    _kline_pattern,
    build_tech_score_table,
    write_tech_score_snapshot,
)


def render_tech_score_panel(root: Path) -> None:
    st.subheader("技术分析 · 指标观察")
    st.caption(
        "表头：品种 / 移动平均 / 动量 / K线形态 / 重叠研究 / 枢轴点 / 基差 / 波动率 / "
        "SuperTrend / Path-A / ST↔Path-A → 合并信号；"
        "五档：强烈看涨、看涨、震荡、看跌、强烈看跌（5/4/3/2/1）。"
        "SuperTrend=日线 ATR10×3（Wilder）趋势带，仅观察；"
        "ST↔Path-A：同向 / 冲突 / 仅ST / 仅Path-A（对照 L1 日信号，不改开仓）。"
    )
    if st.button("重算技术评分", type="primary"):
        with st.spinner("读取本地日线/升贴水并打分…"):
            meta = write_tech_score_snapshot(root)
            st.success(f"已写入 {meta.get('path')} · {meta.get('n')} 品种")
            st.rerun()

    path = root / OUT_REL
    if not path.is_file():
        st.info("尚无评分快照。点「重算技术评分」生成。")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        st.error("tech_score_latest.json 无法解析")
        return
    st.caption(f"快照 {payload.get('asof')}")
    df = pd.DataFrame(payload.get("rows") or [])
    if df.empty:
        st.warning("快照为空")
        return

    if "ST↔Path-A" in df.columns:
        sync_counts = df["ST↔Path-A"].value_counts().to_dict()
        c0, c1, c2, c3 = st.columns(4)
        c0.metric("同向", int(sync_counts.get("同向") or 0))
        c1.metric("冲突", int(sync_counts.get("冲突") or 0))
        c2.metric("仅ST", int(sync_counts.get("仅ST") or 0))
        c3.metric("仅Path-A", int(sync_counts.get("仅Path-A") or 0))
        show = st.radio(
            "筛选 ST↔Path-A",
            ["全部", "同向", "冲突", "仅ST", "仅Path-A"],
            horizontal=True,
            key="tech_st_sync_filter",
        )
        if show != "全部":
            df = df[df["ST↔Path-A"] == show]

    # Prefer watching ST sync columns near the front when present
    preferred = [
        "品种",
        "SuperTrend",
        "Path-A",
        "ST↔Path-A",
        "移动平均",
        "动量指标",
        "K线形态",
        "重叠研究",
        "枢轴点",
        "基差",
        "波动率",
        "合并信号",
        "评分",
    ]
    cols = [c for c in preferred if c in df.columns] + [
        c for c in df.columns if c not in preferred
    ]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    st.caption(
        "合并信号五档：强烈看涨 / 看涨 / 震荡 / 看跌 / 强烈看跌。"
        "SuperTrend 为指标观察，不同步不自动改 Path-A 仓位。"
    )
