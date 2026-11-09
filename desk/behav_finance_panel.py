# -*- coding: utf-8 -*-
"""Behavioral-finance observation proxies for the sentiment page (paper only)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from desk.loaders import load_l1_report, load_universe
from desk.regime_board import load_local_bars
from desk.sentiment_panel import load_sentiment_snapshot


def _closes(bars: list[dict]) -> pd.Series:
    rows = {}
    for b in bars:
        d = str(b.get("date") or "")[:10]
        try:
            rows[d] = float(b["close"])
        except (KeyError, TypeError, ValueError):
            continue
    return pd.Series(rows).sort_index()


def _behav_row(code: str, name: str, closes: pd.Series, sig: dict, sent: dict) -> dict[str, Any]:
    if len(closes) < 60:
        return {
            "品种": f"{code} {name}".strip(),
            "锚定(距60日高低)": "样本不足",
            "过度外推": "—",
            "处置效应代理": "—",
            "拥挤/羊群": "—",
            "行为解读": "震荡观察",
        }
    px = float(closes.iloc[-1])
    hi60 = float(closes.tail(60).max())
    lo60 = float(closes.tail(60).min())
    span = hi60 - lo60
    if span <= 0:
        anchor = "—"
        anchor_bias = 0.0
    else:
        pos = (px - lo60) / span
        if pos >= 0.85:
            anchor, anchor_bias = f"近前高 {pos*100:.0f}%位", 1.0
        elif pos <= 0.15:
            anchor, anchor_bias = f"近前低 {pos*100:.0f}%位", -1.0
        else:
            anchor, anchor_bias = f"区间中性 {pos*100:.0f}%位", 0.0

    r20 = float(closes.iloc[-1] / closes.iloc[-21] - 1.0) if len(closes) > 21 else 0.0
    if abs(r20) >= 0.08:
        extrapolate = f"强外推 r20={r20*100:+.1f}%"
        ext_bias = 1.0 if r20 > 0 else -1.0
    elif abs(r20) >= 0.03:
        extrapolate = f"温和动量 r20={r20*100:+.1f}%"
        ext_bias = 0.5 if r20 > 0 else -0.5
    else:
        extrapolate = f"弱动量 r20={r20*100:+.1f}%"
        ext_bias = 0.0

    # Disposition proxy: price up but seat/sentiment still defensive or vice versa.
    seat = str(sig.get("seat") or "")
    direction = str(sig.get("direction") or "")
    if r20 > 0.03 and ("空" in seat or direction == "空"):
        disposition = "涨中仍偏空·或处置/逢高"
        disp_bias = -0.5
    elif r20 < -0.03 and ("多" in seat or direction == "多"):
        disposition = "跌中仍偏多·或抄底锚定"
        disp_bias = 0.5
    else:
        disposition = "价格与立场大致同向"
        disp_bias = 0.0

    longs = {str(x).upper() for x in (sent.get("longs") or [])}
    shorts = {str(x).upper() for x in (sent.get("shorts") or [])}
    if code in longs and code in shorts:
        crowd = "多空双列·拥挤冲突"
        crowd_bias = 0.0
    elif code in longs:
        crowd = "情绪多头候选"
        crowd_bias = 0.5
    elif code in shorts:
        crowd = "情绪空头候选"
        crowd_bias = -0.5
    else:
        crowd = "未进情绪多空榜"
        crowd_bias = 0.0

    lean = anchor_bias + ext_bias + disp_bias + crowd_bias
    if lean >= 1.5:
        read = "行为偏多（外推/拥挤）"
    elif lean <= -1.5:
        read = "行为偏空（外推/拥挤）"
    elif abs(lean) < 0.5:
        read = "行为中性"
    else:
        read = "行为温和偏向"

    return {
        "品种": f"{code} {name}".strip(),
        "锚定(距60日高低)": anchor,
        "过度外推": extrapolate,
        "处置效应代理": disposition,
        "拥挤/羊群": crowd,
        "行为解读": read,
    }


def build_behav_table(root: Path) -> pd.DataFrame:
    uni = load_universe(root) or {}
    report = load_l1_report(root) or {}
    sent = load_sentiment_snapshot(root) or {}
    sig_by = {
        str(s.get("code") or "").upper(): s
        for s in (report.get("signals") or [])
        if isinstance(s, dict)
    }
    rows = []
    for s in uni.get("symbols") or []:
        if not isinstance(s, dict):
            continue
        code = str(s.get("code") or "").upper()
        if not code:
            continue
        bars, _ = load_local_bars(root, code)
        rows.append(
            _behav_row(
                code,
                str(s.get("name") or ""),
                _closes(bars or []),
                sig_by.get(code) or {},
                sent,
            )
        )
    return pd.DataFrame(rows)


def render_behav_finance_panel(root: Path) -> None:
    st.subheader("行为金融观察（纸面·不计分）")
    st.caption(
        "代理指标：锚定（距60日高低）、过度外推（短动量）、处置效应（价与席位/方向背离）、"
        "拥挤/羊群（是否进情绪多空榜）。不进入 Path-A 评分。"
    )
    with st.spinner("计算行为金融代理…"):
        df = build_behav_table(root)
    if df.empty:
        st.info("无宇宙品种可算。")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)
    lean_up = int(df["行为解读"].astype(str).str.contains("偏多").sum())
    lean_dn = int(df["行为解读"].astype(str).str.contains("偏空").sum())
    st.caption(f"行为偏多 {lean_up} · 偏空 {lean_dn} · 其余中性/温和 · E1 影子口径，不下单。")
