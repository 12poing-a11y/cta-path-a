# -*- coding: utf-8 -*-
"""Streamlit panel: prediction log + T+1/3/5 attribution (paper)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


PRED_UI_BUILD = "2026-10-29e · 品种=期号+中文"


def render_prediction_panel(root: Path) -> None:
    import streamlit as st

    from desk.loaders import format_variety_label, load_universe
    from prediction_log import load_day, write_desk_predictions
    from prediction_score import score_predictions

    st.subheader("预测记录与归因（纸面）")
    st.caption(
        "总盘面结论 → 1/3/5 交易日预测 → 到期方向归因。"
        "不改 Path-A 手数，不下实盘。"
        f" · 界面 `{PRED_UI_BUILD}`"
    )

    names: dict[str, str] = {}
    uni = load_universe(root) or {}
    for row in uni.get("symbols") or []:
        if isinstance(row, dict):
            code = str(row.get("code") or "").upper()
            if code:
                names[code] = str(row.get("name") or "")

    c1, c2, c3 = st.columns(3)
    with c1:
        do_write = st.button("写入今日预测", key="pred_write")
    with c2:
        do_score = st.button("刷新到期归因", key="pred_score")
    with c3:
        st.write("")

    if do_write:
        out = write_desk_predictions(root)
        if out.get("ok"):
            st.success(f"已写入 {out.get('n')} 条 · asof={out.get('asof')}")
        else:
            st.warning(f"写入失败：{out.get('error')}")

    if do_score:
        out = score_predictions(root)
        if out.get("ok"):
            s = out.get("summary") or {}
            st.success(
                f"归因完成 · 命中率 {s.get('hit_rate_pct')}% "
                f"(命中{s.get('hits')}/错{s.get('misses')}/无法判断{s.get('voids')}/待定{s.get('pending')})"
            )
        else:
            st.warning(f"归因失败：{out.get('error')}")

    latest = load_day(root)
    summary_path = root / "lab" / "research" / "predictions" / "score_summary.json"
    summary = None
    if summary_path.is_file():
        import json

        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary = None

    if summary and isinstance(summary.get("summary"), dict):
        s = summary["summary"]
        m0, m1, m2, m3 = st.columns(4)
        m0.metric("命中率", f"{s.get('hit_rate_pct')}%" if s.get("hit_rate_pct") is not None else "—")
        m1.metric("命中", s.get("hits") or 0)
        m2.metric("方向错误", s.get("misses") or 0)
        m3.metric("待定", s.get("pending") or 0)

    if not latest:
        st.info("尚无预测日志。点「写入今日预测」或跑完 daily_update 后自动写入。")
        return

    st.markdown(f"### 当日预测 · asof `{latest.get('asof')}` · n={latest.get('n')}")
    book = latest.get("portfolio") or {}
    if book:
        st.caption(f"组合总盘面：{book.get('结论') or book.get('label') or '—'} · {book.get('note') or ''}")

    rows = []
    for p in latest.get("predictions") or []:
        if not isinstance(p, dict):
            continue
        scores = p.get("scores") or {}
        def _cell(h: str) -> str:
            sc = scores.get(h) or {}
            if sc.get("status") == "pending":
                return "待定"
            cls = sc.get("class") or "—"
            rp = sc.get("ret_pct")
            if rp is None:
                return str(cls)
            return f"{cls} ({rp:+.2f}%)"

        src = p.get("sources") or {}
        code = str(p.get("code") or "").upper()
        rows.append(
            {
                "品种": format_variety_label(code, names.get(code, ""), root=root),
                "方向": p.get("direction"),
                "结论": p.get("conclusion"),
                "把握%": p.get("conviction_pct"),
                "对照": src.get("align"),
                "T+1": _cell("1"),
                "T+3": _cell("3"),
                "T+5": _cell("5"),
                "证伪条件": p.get("falsify"),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with st.expander("原始 JSON"):
        st.json(latest)
