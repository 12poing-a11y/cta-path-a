# -*- coding: utf-8 -*-
"""Desk panel: equity-index timing signal → suggested weight."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.loaders import load_json  # noqa: E402
from equity_timing import (  # noqa: E402
    load_spec,
    pack_day,
    suggested_weight,
)


def render_equity_timing(root: Path | None = None) -> None:
    root = root or ROOT
    st.subheader("股指择时信号")
    spec = load_spec(root / "external" / "equity_timing_spec.json")
    st.caption(
        f"标的：{'、'.join(t['name'] for t in spec.get('targets') or [])}。"
        f" {spec.get('horizon', {}).get('example', '')}"
        " 合成越小越空、越大越多；建议权重按桶映射。低胜率高赔率，研究用。"
    )

    latest = load_json(root / "external" / "equity_timing_latest.json") or {}
    asof = latest.get("asof") or "—"
    st.write(f"asof：**{asof}** · 预测窗：t+1 开 → t+2 开")

    rows = []
    targets = (latest.get("targets") or {})
    name_by = {t["code"]: t["name"] for t in spec.get("targets") or []}
    for code, payload in targets.items():
        if not isinstance(payload, dict):
            continue
        comp = payload.get("composite")
        cats = payload.get("categories") or {}
        if cats and comp is None:
            packed = pack_day(asof=str(asof), target=code, categories=cats)
            comp = packed.get("composite")
            w = {
                "weight": packed.get("suggested_weight"),
                "label": packed.get("suggested_weight_label"),
                "bucket": packed.get("bucket"),
            }
        else:
            w = suggested_weight(comp if comp is not None else None)
        rows.append(
            {
                "指数": name_by.get(code, code),
                "代码": code,
                "合成信号": comp,
                "建议权重": w.get("label"),
                "权重数值": w.get("weight"),
                "分桶": w.get("bucket"),
            }
        )

    if not rows or all(r.get("合成信号") is None for r in rows):
        st.info(
            "尚未写入当日信号。编辑 `external/equity_timing_latest.json` "
            "填入各指数 `composite`（-1~1）或 `categories` 因子后刷新。"
        )
        demo = pd.DataFrame(
            [
                {"合成信号": -0.5, **{k: v for k, v in suggested_weight(-0.5).items() if k != "composite"}},
                {"合成信号": -0.2, **{k: v for k, v in suggested_weight(-0.2).items() if k != "composite"}},
                {"合成信号": 0.0, **{k: v for k, v in suggested_weight(0.0).items() if k != "composite"}},
                {"合成信号": 0.2, **{k: v for k, v in suggested_weight(0.2).items() if k != "composite"}},
                {"合成信号": 0.5, **{k: v for k, v in suggested_weight(0.5).items() if k != "composite"}},
            ]
        )
        st.markdown("**权重分桶示意**")
        st.dataframe(demo, width="stretch", hide_index=True)
    else:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with st.expander("数据说明"):
        st.markdown(
            """
1. 预测标的：上证50、沪深300、中证500、中证1000 的**日度收益率**  
2. 每天收盘后计算；信号预测 **t+1 开盘 → t+2 开盘**  
3. 单因子 ∈ {-1,-0.5,0,0.5,1}；分类=类内均值；合成=全部单因子均值 ∈ [-1,1]  
4. 合成 → 建议权重：(-1,-0.3]→-100%，(-0.3,-0.1]→-50%，(-0.1,0.1]→0%，(0.1,0.3]→50%，(0.3,1]→100%  
5. 低胜率高赔率：回测胜率约 40%–50%，盈亏比 > 2  
            """
        )
        st.json(
            {
                "style": spec.get("style"),
                "horizon": spec.get("horizon"),
            }
        )
