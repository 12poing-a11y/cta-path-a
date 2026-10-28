# -*- coding: utf-8 -*-
"""Paper-only MDS+EHI sentiment sleeve panel (ChatGPT share)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from desk.loaders import format_variety_label, load_json, load_universe


def sentiment_score_from_p3(p3: float | None) -> float | None:
    """Map portfolio_p3 in [-1, 1] → 0–100 research score."""
    if p3 is None:
        return None
    try:
        x = float(p3)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, (x + 1.0) / 2.0 * 100.0)), 1)


def load_sentiment_snapshot(root: Path) -> dict[str, Any] | None:
    latest = root / "data" / "sentiment_mds" / "latest.json"
    if not latest.is_file():
        return None
    return load_json(latest)


def stance_to_direction(stance: str | None) -> str:
    s = str(stance or "").lower()
    if s == "risk_on":
        return "多"
    if s == "risk_off":
        return "空"
    if s == "neutral":
        return "震荡"
    return "样本不足"


def sentiment_verdict(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Clear 多/空/震荡 + conviction % from portfolio_p3 and long/short breadth."""
    if not snap:
        return {
            "direction": "样本不足",
            "conviction_pct": 0.0,
            "label": "样本不足",
            "p3": None,
            "n_long": 0,
            "n_short": 0,
        }
    p3 = snap.get("portfolio_p3")
    try:
        p3_f = float(p3) if p3 is not None else 0.0
    except (TypeError, ValueError):
        p3_f = 0.0
    direction = stance_to_direction(snap.get("stance"))
    # Prefer p3 magnitude if stance missing/neutral but |p3| strong
    if direction == "震荡" and p3_f > 0.15:
        direction = "多"
    elif direction == "震荡" and p3_f < -0.15:
        direction = "空"
    elif direction == "样本不足":
        if p3_f > 0.15:
            direction = "多"
        elif p3_f < -0.15:
            direction = "空"
        else:
            direction = "震荡"

    longs = list(snap.get("longs") or [])
    shorts = list(snap.get("shorts") or [])
    n_l, n_s = len(longs), len(shorts)
    n_sig = n_l + n_s
    breadth = abs(n_l - n_s) / n_sig if n_sig else 0.0
    # Directed: base 35 + |P3|×45 + 多空广度×20；震荡封顶 32。
    if direction in ("多", "空"):
        raw = 35.0 + abs(p3_f) * 45.0 + breadth * 20.0
    else:
        raw = min(32.0, abs(p3_f) * 40.0 + breadth * 15.0)
    conviction = round(max(0.0, min(100.0, raw)), 1)
    return {
        "direction": direction,
        "conviction_pct": conviction,
        "label": f"{direction} · 把握 {conviction:.0f}%",
        "p3": round(p3_f, 4),
        "n_long": n_l,
        "n_short": n_s,
        "breadth": round(breadth, 3),
    }


def _name_map(root: Path) -> dict[str, str]:
    uni = load_universe(root) or {}
    out: dict[str, str] = {}
    for row in uni.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").upper()
        if code:
            out[code] = str(row.get("name") or "")
    return out


def _path_a_sides(root: Path) -> dict[str, str]:
    """code -> 多/空 from paper positions and daily selected."""
    out: dict[str, str] = {}
    paper = load_json(root / "paper_book_latest.json") or {}
    for code, pos in (paper.get("positions") or {}).items():
        if not isinstance(pos, dict):
            continue
        d = str(pos.get("direction") or "")
        if d in ("多", "空"):
            out[str(code).upper()] = d
    report = load_json(root / "l1_report_risk15.json") or load_json(root / "l1_report.json") or {}
    for sig in report.get("signals") or []:
        if not isinstance(sig, dict) or not sig.get("selected"):
            continue
        code = str(sig.get("code") or "").upper()
        d = str(sig.get("direction") or "")
        if code and d in ("多", "空"):
            out[code] = d
    return out


def _signal_zh(sig: Any) -> str:
    try:
        v = int(sig)
    except (TypeError, ValueError):
        return "观望"
    if v > 0:
        return "多"
    if v < 0:
        return "空"
    return "观望"


def render_sentiment_panel(root: Path) -> None:
    import streamlit as st

    st.subheader("情绪袖套 MDS+EHI（纸面对照）")
    st.caption(
        "MDS（席位流与价格同/背离）+ EHI（|净持仓|/OI）+ 软 P3。"
        "仅纸面对照，不改 Path-A 手数，不下实盘单。"
        "结论直接给多/空/震荡；把握%由 |P3| 与多空候选广度合成。"
    )
    snap = load_sentiment_snapshot(root)
    if not snap:
        st.info("尚无 sentiment 快照。跑完 daily_update.py 后会出现在 data/sentiment_mds/。")
        return

    verdict = sentiment_verdict(snap)
    score = sentiment_score_from_p3(snap.get("portfolio_p3"))
    names = _name_map(root)

    st.markdown("### 情绪结论")
    c0, c1, c2, c3, c4 = st.columns(5)
    c0.metric("方向", verdict["direction"])
    c1.metric("把握", f"{verdict['conviction_pct']:.0f}%")
    c2.metric("组合P3", verdict.get("p3"))
    c3.metric("本层得分", score if score is not None else "—")
    c4.metric("asof", snap.get("asof"))
    st.caption(
        f"{verdict['label']} · 多头候选 {verdict['n_long']} / 空头候选 {verdict['n_short']} · "
        f"live={'是' if snap.get('live') else '否'} · 研究用，非下单指令"
    )

    longs = [str(x).upper() for x in (snap.get("longs") or [])]
    shorts = [str(x).upper() for x in (snap.get("shorts") or [])]

    def _variety_label(code: str) -> str:
        """Single 品种 column: contract period + Chinese name (no separate 代码 col)."""
        return format_variety_label(code, names.get(code, ""), root=root)

    def _zh_list(codes: list[str]) -> str:
        return "、".join(_variety_label(c) for c in codes) if codes else "—"

    st.write(f"**多头候选**：{_zh_list(longs)}")
    st.write(f"**空头候选**：{_zh_list(shorts)}")

    path_a = _path_a_sides(root)
    compare_rows = []
    for code in sorted(set(longs) | set(shorts) | set(path_a)):
        sent = "多" if code in longs else ("空" if code in shorts else "—")
        pa = path_a.get(code) or "—"
        if sent in ("多", "空") and pa in ("多", "空"):
            align = "同向" if sent == pa else "冲突"
        elif sent in ("多", "空") and pa == "—":
            align = "仅情绪"
        elif pa in ("多", "空") and sent == "—":
            align = "仅Path-A"
        else:
            align = "—"
        compare_rows.append(
            {
                "品种": _variety_label(code),
                "情绪方向": sent,
                "Path-A持仓/日选": pa,
                "对照": align,
            }
        )
    if compare_rows:
        st.markdown("**与 Path-A 对照**")
        st.dataframe(pd.DataFrame(compare_rows), width="stretch", hide_index=True)

    syms = snap.get("symbols") or []
    if syms:
        st.markdown("**品种明细**")
        rows = []
        for s in syms:
            if not isinstance(s, dict):
                continue
            code = str(s.get("code") or "").upper()
            rows.append(
                {
                    "品种": _variety_label(code),
                    "MDS同向": s.get("mds"),
                    "拥挤EHI": s.get("ehi"),
                    "P3得分": s.get("p3"),
                    "信号": _signal_zh(s.get("signal")),
                    "权重": s.get("w_norm"),
                    "净持仓": s.get("net"),
                    "日收益": s.get("ret_1d"),
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    with st.expander("原始 JSON"):
        st.json({**snap, "verdict": verdict})
