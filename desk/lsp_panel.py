# -*- coding: utf-8 -*-
"""LSP sweep research panel (CF first; not a formal Path-A signal)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load(root: Path, timeframe: str = "15m") -> dict[str, Any]:
    path = root / "lab" / "research" / "lsp" / f"lsp_CF_{timeframe}_latest.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def render_lsp_panel(st, root: Path) -> None:
    st.caption(
        "流动性扫荡（LSP）为 **Research**：只统计真假突破条件概率，"
        "**不会**改 Path-A 入场。数据来自 CF 分钟缓存。"
    )
    tf = st.selectbox("周期", ["15m", "60m"], index=0)
    payload = _load(root, tf)
    if not payload:
        st.info(
            f"尚无 `{tf}` 产物。仓库根目录运行：`python lab/scripts/run_lsp_cf.py --period {tf[:-1]}`"
        )
        return
    stats = payload.get("stats") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("事件数", payload.get("n_events") or stats.get("n_events"))
    c2.metric("假突破概率", (stats.get("outcome_probs") or {}).get("fake_break_reversal"))
    c3.metric("真突破概率", (stats.get("outcome_probs") or {}).get("true_break_continuation"))
    c4.metric("无效扫荡", (stats.get("outcome_probs") or {}).get("invalid_sweep"))
    st.caption(
        f"均 MFE={stats.get('avg_mfe_atr')} ATR · 均 MAE={stats.get('avg_mae_atr')} ATR · "
        f"bars={payload.get('n_bars')} · status={payload.get('status')}"
    )
    by_dir = stats.get("by_direction") or {}
    if by_dir:
        st.subheader("按刺穿方向")
        st.json(by_dir)
    res = stats.get("resonance") or {}
    if res:
        st.subheader("15m↔60m 共振")
        st.json(res)
        st.caption("共振事件与非共振事件的结果分布对比（Research）。")
    vol = {
        "高量≥1.2": stats.get("high_volume_ge_1_2"),
        "低量<1.2": stats.get("low_volume_lt_1_2"),
    }
    st.subheader("成交量分层")
    st.json(vol)
    tail = payload.get("events_tail") or []
    if tail:
        st.subheader("最近事件")
        rows = [
            {
                "时间": e.get("timestamp"),
                "方向": e.get("break_direction"),
                "结果": e.get("outcome"),
                "突破ATR": e.get("break_size_atr"),
                "量比": e.get("volume_ratio"),
                "MFE": e.get("mfe"),
                "MAE": e.get("mae"),
                "收回根数": e.get("reclaim_bars"),
            }
            for e in reversed(tail[-30:])
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
