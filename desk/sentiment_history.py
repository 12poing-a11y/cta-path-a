# -*- coding: utf-8 -*-
"""情绪量化 MDS+EHI 影子历史页 —「影子·不计分」.

Reads data/sentiment_mds/shadow/sentiment_YYYYMMDD.json only. Never writes,
never touches latest.json or live scoring. Next-day returns prefer
.cache/history/<CODE>0.json, then sina continuous folders.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

LABEL = "E1·影子·不计分"


def load_shadow_snapshots(root: Path) -> list[dict]:
    d = Path(root) / "data" / "sentiment_mds" / "shadow"
    out = []
    for p in sorted(d.glob("sentiment_*.json")):
        try:
            snap = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(snap, dict) and snap.get("asof"):
            out.append(snap)
    return out


def _bars_to_close_series(bars: list) -> pd.Series | None:
    rows: dict[str, float] = {}
    if not isinstance(bars, list):
        return None
    for b in bars:
        if not isinstance(b, dict) or b.get("close") is None:
            continue
        d = str(b.get("date") or "").replace("-", "")[:8]
        if len(d) != 8 or not d.isdigit():
            continue
        try:
            rows[d] = float(b["close"])
        except (TypeError, ValueError):
            continue
    if not rows:
        return None
    return pd.Series(rows).sort_index()


def _close_series(root: Path) -> dict[str, pd.Series]:
    """Map CODE -> close series keyed YYYYMMDD.

    Prefer merged chart history (free+gap fill), then overlay newer sina folders.
    """
    root = Path(root)
    out: dict[str, pd.Series] = {}

    hist = root / ".cache" / "history"
    if hist.is_dir():
        for f in hist.glob("*0.json"):
            try:
                bars = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            s = _bars_to_close_series(bars)
            if s is not None:
                out[f.stem[:-1].upper()] = s

    sina = root / ".cache" / "sina"
    dirs = sorted([p for p in sina.glob("*") if p.is_dir()]) if sina.is_dir() else []
    for d in dirs:  # later dirs override earlier on overlapping dates
        for f in d.glob("*0.json"):
            try:
                bars = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            s = _bars_to_close_series(bars)
            if s is None:
                continue
            code = f.stem[:-1].upper()
            if code in out:
                merged = out[code].copy()
                merged.update(s)
                out[code] = merged.sort_index()
            else:
                out[code] = s
    return out


def _next_ret(s: pd.Series | None, ymd: str) -> float | None:
    if s is None or ymd not in s.index:
        return None
    i = s.index.get_loc(ymd)
    if isinstance(i, slice):
        i = i.start
    if i + 1 >= len(s):
        return None
    c0, c1 = float(s.iloc[i]), float(s.iloc[i + 1])
    if c0 <= 0:
        return None
    return c1 / c0 - 1.0


def shadow_history_frame(root: Path) -> pd.DataFrame:
    closes = _close_series(root)
    rows = []
    for snap in load_shadow_snapshots(root):
        ymd = str(snap["asof"])[:8]
        syms = snap.get("symbols") or []
        ls_num, ls_den, mkt = 0.0, 0.0, []
        for s in syms:
            r = _next_ret(closes.get(str(s.get("code")).upper()), ymd)
            if r is None:
                continue
            mkt.append(r)
            sig, w = float(s.get("signal") or 0), float(s.get("w_norm") or 0)
            if sig and w:
                ls_num += sig * w * r
                ls_den += w
        rows.append(
            {
                "asof": ymd,
                "p3": snap.get("portfolio_p3"),
                "stance": snap.get("stance"),
                "n": snap.get("n"),
                "多": len(snap.get("longs") or []),
                "空": len(snap.get("shorts") or []),
                "次日等权%": round(100 * sum(mkt) / len(mkt), 3) if mkt else None,
                "次日影子组合%": round(100 * ls_num / ls_den, 3) if ls_den else None,
                "次日覆盖": len(mkt),
                "live": bool(snap.get("live")),
            }
        )
    return pd.DataFrame(rows)


def stance_summary(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["次日等权%"])
    if d.empty:
        return pd.DataFrame()
    g = d.groupby("stance")["次日等权%"]
    return pd.DataFrame(
        {
            "天数": g.size(),
            "次日等权均值%": g.mean().round(3),
            "次日上涨占比%": (g.apply(lambda x: (x > 0).mean()) * 100).round(1),
        }
    ).reset_index()


def render_sentiment_history_tab(root: Path) -> None:
    import plotly.graph_objects as go
    import streamlit as st

    st.subheader(f"情绪量化 MDS+EHI 历史 —「{LABEL}」")
    st.warning(
        f"【{LABEL}】仅影子观察：不进 Path-A 评分、不改 latest.json、不下单。"
        "缺日请跑 scripts/run_sentiment_shadow_range.py 补齐。"
    )
    df = shadow_history_frame(root)
    if df.empty:
        st.info("data/sentiment_mds/shadow/ 下没有影子快照。")
        return
    if df["live"].any():
        st.error("有快照 live=true，与影子口径不符，待核。")

    missing_ret = int(df["次日等权%"].isna().sum())
    if missing_ret:
        st.caption(
            f"次日收益空缺 {missing_ret} 行：通常是样本末日尚无下一根日线，"
            "或本地 .cache/history / sina 缺该日收盘。"
        )

    fig = go.Figure()
    fig.add_bar(x=df["asof"], y=df["次日等权%"], name="次日等权收益%", yaxis="y2", opacity=0.45)
    fig.add_bar(x=df["asof"], y=df["次日影子组合%"], name="次日影子组合%", yaxis="y2", opacity=0.45)
    fig.add_scatter(x=df["asof"], y=df["p3"], name="portfolio p3", mode="lines+markers")
    fig.update_layout(
        title=f"p3 走势 vs 次日收益（{LABEL}）",
        xaxis={"type": "category"},
        yaxis={"title": "p3"},
        yaxis2={"title": "次日%", "overlaying": "y", "side": "right"},
        barmode="group",
        height=420,
    )
    st.plotly_chart(fig, width="stretch")
    summ = stance_summary(df)
    if not summ.empty:
        st.markdown("**按 stance 分组的次日等权收益**（观察，不计分）")
        st.dataframe(summ, width="stretch", hide_index=True)
    st.dataframe(df.drop(columns=["live"]), width="stretch", hide_index=True)
    st.caption(
        "次日收益 = .cache/history 优先，否则 sina 连续合约收盘对收盘；"
        "最后一天无次日数据为空。影子组合 = Σ signal·w_norm·次日收益 / Σ w_norm。"
    )
