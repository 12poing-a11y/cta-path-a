# -*- coding: utf-8 -*-
"""Paper-only MDS+EHI sentiment sleeve panel (ChatGPT share)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from desk.loaders import load_json


def render_sentiment_panel(root: Path) -> None:
    st.subheader("情绪袖套 MDS+EHI（纸面对照）")
    st.caption(
        "来自 ChatGPT 三层情绪策略简化落地：MDS（席位流与价格同/背离）+ EHI（|净持仓|/OI）。"
        "仅纸面对照，不改 Path-A 手数，不下实盘单。"
    )
    latest = root / "data" / "sentiment_mds" / "latest.json"
    snap: dict[str, Any] | None = load_json(latest) if latest.is_file() else None
    if not snap:
        st.info("尚无 sentiment 快照。跑完 daily_update.py 后会出现在 data/sentiment_mds/。")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("asof", snap.get("asof"))
    c2.metric("stance", snap.get("stance"))
    c3.metric("portfolio P3", snap.get("portfolio_p3"))
    c4.metric("live", "否" if not snap.get("live") else "是")
    st.write(
        f"多头候选: {', '.join(snap.get('longs') or []) or '—'} ｜ "
        f"空头候选: {', '.join(snap.get('shorts') or []) or '—'}"
    )
    syms = snap.get("symbols") or []
    if syms:
        df = pd.DataFrame(syms)
        cols = [c for c in ("code", "mds", "ehi", "p3", "signal", "w_norm", "net", "ret_1d") if c in df.columns]
        st.dataframe(df[cols] if cols else df, width="stretch", hide_index=True)
    with st.expander("原始 JSON"):
        st.json(snap)
