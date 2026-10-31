# -*- coding: utf-8 -*-
"""HV20/HV60 已实现波动率分位面板（不含 IV）.

Uses local sina continuous daily bars (.cache/sina/<dir>/<CODE>0.json) and the
ATR in l1_report.json. HV = std(log close-to-close returns) * sqrt(252) * 100.
Percentile = rank of today's HV within its own trailing LOOKBACK days.
Continuous contracts include roll gaps -> HV may be inflated on roll days (待核).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

LOOKBACK = 750  # ~3 years of trading days


def _closes(root: Path) -> dict[str, pd.Series]:
    base = Path(root) / ".cache" / "sina"
    out: dict[str, pd.Series] = {}
    for d in sorted(p for p in base.glob("*") if p.is_dir()) if base.is_dir() else []:
        for f in d.glob("*0.json"):
            try:
                bars = json.loads(f.read_text(encoding="utf-8"))
                s = pd.Series({str(b["date"]): float(b["close"]) for b in bars if b.get("close")}).sort_index()
                out[f.stem[:-1].upper()] = s[s > 0]
            except Exception:
                continue
    return out


def hv_stats(close: pd.Series, lookback: int = LOOKBACK) -> dict:
    lr = np.log(close).diff().dropna()
    if len(lr) < 61:
        return {}
    hv20 = lr.rolling(20).std() * math.sqrt(252) * 100
    hv60 = lr.rolling(60).std() * math.sqrt(252) * 100

    def pct(series: pd.Series) -> float | None:
        s = series.dropna().iloc[-lookback:]
        if s.empty:
            return None
        return round(float((s <= s.iloc[-1]).mean() * 100), 1)

    return {
        "bar_date": str(close.index[-1]),
        "HV20%": round(float(hv20.iloc[-1]), 2),
        "HV60%": round(float(hv60.iloc[-1]), 2),
        "HV20分位": pct(hv20),
        "HV60分位": pct(hv60),
        "HV20/HV60": round(float(hv20.iloc[-1] / hv60.iloc[-1]), 2) if hv60.iloc[-1] else None,
    }


def hv_frame(root: Path, premium_atr_mult: float = 1.0) -> pd.DataFrame:
    try:
        rep = json.loads((Path(root) / "l1_report.json").read_text(encoding="utf-8"))
    except Exception:
        rep = {}
    closes = _closes(root)
    rows = []
    for s in rep.get("signals") or []:
        code = str(s.get("code") or "").upper()
        st = hv_stats(closes[code]) if code in closes else {}
        if not st:
            continue
        atr, close = s.get("atr"), s.get("close")
        atr_pct = round(100 * float(atr) / float(close), 2) if atr and close else None
        rows.append(
            {
                "code": code,
                "name": s.get("name"),
                **st,
                "ATR%": atr_pct,
                "ATR年化%≈": round(atr_pct * math.sqrt(252) / 1.25, 2) if atr_pct else None,
                "ATR合成权利金": round(premium_atr_mult * float(atr), 2) if atr else None,
                "权利金/价%": round(100 * premium_atr_mult * float(atr) / float(close), 2) if atr and close else None,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("HV20分位", ascending=False).reset_index(drop=True)
    return df


def render_hv_panel(root: Path, premium_atr_mult: float) -> None:
    import streamlit as st

    st.subheader("已实现波动率 HV20/HV60 分位（不含 IV）")
    df = hv_frame(root, premium_atr_mult)
    if df.empty:
        st.info("本地无 sina 连续日线或 l1_report，HV 面板跳过。")
        return
    hi = df[df["HV20分位"] >= 80]["code"].tolist()
    lo = df[df["HV20分位"] <= 20]["code"].tolist()
    st.caption(
        f"HV20 高分位(≥80)：{', '.join(hi) or '—'} ｜ 低分位(≤20)：{', '.join(lo) or '—'} · "
        f"分位窗口 {LOOKBACK} 日 · 权利金 = premium_atr_mult({premium_atr_mult}) × ATR"
    )
    st.dataframe(df, width="stretch", hide_index=True)
    st.caption(
        "HV=对数收益年化标准差；ATR年化≈ATR%×√252/1.25（ATR→σ 粗换算，仅对照）。"
        "连续合约含换月跳空，换月日附近 HV 偏高，待核。没有隐含波动率（IV）数据。"
    )
