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
    st.subheader("技术分析打分表")
    st.caption(
        "表头：品种 / 移动平均 / 动量 / K线形态 / 重叠研究 / 枢轴点 / 基差 / 波动率 → 合并信号；"
        "五档：强烈看涨、看涨、震荡、看跌、强烈看跌（5/4/3/2/1）。"
        "K线形态=近20日结构（上升 / 下降 / 箱体震荡）；基差=近次月升贴水；波动率=HV20及分位。"
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
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(
        "合并信号五档：强烈看涨 / 看涨 / 震荡 / 看跌 / 强烈看跌。"
        "K线形态仅三档：上升、下降、箱体震荡（近20日高低点+斜率）；均线与动量为主。"
    )
