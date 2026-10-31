# -*- coding: utf-8 -*-
"""晨报对照卡：盘前结论（dir_used）vs 15:30 L1 信号方向，差异高亮.

Premarket source: <DESK_PREMARKET_DIR>/<YYYYMMDD>-premarket/scores_premarket.csv
(default /workspace/desk/project-log/runs). Read-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

DEFAULT_DIR = "/workspace/desk/project-log/runs"
_MAP = {"偏多": "多", "偏空": "空", "震荡": "空仓"}


def premarket_dir() -> Path:
    return Path(os.environ.get("DESK_PREMARKET_DIR", DEFAULT_DIR))


def load_premarket(ymd: str, base: Path | None = None) -> tuple[pd.DataFrame, Path | None]:
    base = base or premarket_dir()
    p = base / f"{ymd}-premarket" / "scores_premarket.csv"
    if not p.is_file():
        return pd.DataFrame(), None
    try:
        return pd.read_csv(p, dtype=str), p
    except Exception:
        return pd.DataFrame(), p


def compare_frame(root: Path, base: Path | None = None) -> dict:
    try:
        rep = json.loads((Path(root) / "l1_report.json").read_text(encoding="utf-8"))
    except Exception:
        rep = {}
    asof = str(rep.get("asof") or "")[:8]
    pm, path = load_premarket(asof, base) if asof else (pd.DataFrame(), None)
    out = {"asof": asof, "path": str(path) if path else None, "df": pd.DataFrame(), "summary": {}}
    if pm.empty or "product" not in pm.columns:
        return out
    pm = pm.set_index(pm["product"].str.upper())
    rows = []
    for s in rep.get("signals") or []:
        code = str(s.get("code") or "").upper()
        if code not in pm.index:
            continue
        r = pm.loc[code]
        pre = str(r.get("dir_used") or "")
        pre_d = _MAP.get(pre, pre)
        l1_d = str(s.get("direction") or "")
        if pre_d == l1_d:
            kind = "一致"
        elif "空仓" in (pre_d, l1_d):
            kind = "一方中性"
        else:
            kind = "反向"
        rows.append(
            {
                "code": code,
                "name": s.get("name"),
                "盘前dir_used": pre,
                "盘前分": r.get("score_adj"),
                "夜盘ATR倍": r.get("night_atr_mult"),
                "过闸": r.get("gate_05atr"),
                "15:30方向": l1_d,
                "align": s.get("align"),
                "入选": bool(s.get("selected")),
                "对照": kind,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        order = {"反向": 0, "一方中性": 1, "一致": 2}
        df = df.sort_values("对照", key=lambda x: x.map(order)).reset_index(drop=True)
        out["summary"] = df["对照"].value_counts().to_dict()
    out["df"] = df
    return out


def render_premarket_card(root: Path) -> None:
    import streamlit as st

    st.subheader("晨报对照（盘前结论 vs 15:30 信号）· 描述性对照，不计分")
    res = compare_frame(root)
    if res["df"].empty:
        st.info(
            f"未找到 asof={res['asof'] or '—'} 的盘前得分表"
            f"（{premarket_dir()}/<日期>-premarket/scores_premarket.csv），对照卡跳过。"
        )
        return
    s = res["summary"]
    c1, c2, c3 = st.columns(3)
    c1.metric("反向", s.get("反向", 0))
    c2.metric("一方中性", s.get("一方中性", 0))
    c3.metric("一致", s.get("一致", 0))
    df = res["df"]

    def _hl(row):
        color = {"反向": "background-color:#f8d7da", "一方中性": "background-color:#fff3cd"}.get(row["对照"], "")
        return [color] * len(row)

    st.dataframe(df.style.apply(_hl, axis=1), width="stretch", hide_index=True)
    st.caption(
        f"盘前=当日 07:3x 定稿前的量化 dir_used（含上一夜盘），15:30=当日日盘收盘信号；只看差异，不出指令。来源 {res['path']}"
    )
