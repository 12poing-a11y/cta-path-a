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


def total_board_conclusion(
    *,
    align: str,
    path_a: str,
    sent: str,
    vol_conclusion: str,
    sentiment_conviction: float = 0.0,
) -> dict[str, Any]:
    """Merge Path-A对照 + 波动盘面 → one paper conclusion per name."""
    vol = str(vol_conclusion or "观望").strip() or "观望"
    pa = str(path_a or "—").strip()
    se = str(sent or "—").strip()
    al = str(align or "—").strip()

    # Vol alerts / research take explicit priority when actionable.
    if vol in ("止盈预警", "止损预警"):
        return {"结论": vol, "note": "波动/最终信号预警优先"}
    if vol == "波动率卖方研究":
        return {"结论": "波动率卖方研究", "note": "卖波标注；方向以观望为主，不改期货开仓"}
    if vol == "日历价差研究":
        return {"结论": "日历价差研究", "note": "近远月结构候选"}

    if al == "冲突" and sentiment_conviction >= 60:
        return {
            "结论": "观望",
            "note": "情绪与Path-A冲突且把握高 → 总盘面观望",
        }

    if vol in ("偏多研究", "偏空研究"):
        # Conflict with Path-A / sentiment → soften to 观望
        want = "多" if "偏多" in vol else "空"
        if pa in ("多", "空") and pa != want:
            return {"结论": "观望", "note": f"波动{vol}与Path-A{pa}不一致"}
        if se in ("多", "空") and se != want and sentiment_conviction >= 60:
            return {"结论": "观望", "note": f"波动{vol}与情绪{se}硬冲突"}
        return {"结论": vol, "note": "波动方向研究，Path-A/情绪未硬冲突"}

    # Vol 观望：fall back to Path-A + sentiment alignment.
    if al == "同向" and pa in ("多", "空"):
        return {
            "结论": f"偏{pa}研究",
            "note": "Path-A与情绪同向；波动未给独立方向",
        }
    if al == "仅Path-A" and pa in ("多", "空"):
        return {
            "结论": f"偏{pa}研究",
            "note": "仅Path-A有方向；波动观望",
        }
    if al == "仅情绪" and se in ("多", "空") and sentiment_conviction >= 60:
        return {
            "结论": "观望",
            "note": "仅情绪有方向、无Path-A确认 → 不单独开仓",
        }
    if al == "冲突":
        return {"结论": "观望", "note": "情绪与Path-A冲突"}

    return {"结论": "观望", "note": "Path-A与波动均无清晰方向"}


def portfolio_total_verdict(
    rows: list[dict[str, Any]],
    *,
    sentiment_direction: str,
    sentiment_conviction: float,
) -> dict[str, Any]:
    """One book-level line from per-name 总结论."""
    if not rows:
        return {
            "结论": "观望",
            "note": "无对照品种",
            "label": "观望",
        }
    counts: dict[str, int] = {}
    for r in rows:
        c = str(r.get("总结论") or "观望")
        counts[c] = counts.get(c, 0) + 1
    long_n = counts.get("偏多研究", 0)
    short_n = counts.get("偏空研究", 0)
    sell_n = counts.get("波动率卖方研究", 0)
    alert_n = counts.get("止盈预警", 0) + counts.get("止损预警", 0)
    watch_n = counts.get("观望", 0)

    if alert_n:
        return {
            "结论": "有预警",
            "note": f"止盈/止损预警 {alert_n} 个品种优先处理",
            "label": f"有预警 · {alert_n}",
            "counts": counts,
        }
    if sell_n and sell_n >= max(long_n, short_n, 1):
        return {
            "结论": "波动率卖方研究",
            "note": f"卖方研究 {sell_n}；多{long_n}/空{short_n}；情绪{sentiment_direction}{sentiment_conviction:.0f}%",
            "label": f"波动率卖方研究 · {sell_n}",
            "counts": counts,
        }
    if long_n > short_n and long_n > 0:
        return {
            "结论": "偏多研究",
            "note": f"总盘面偏多 {long_n} vs 偏空 {short_n}；观望 {watch_n}；情绪{sentiment_direction}",
            "label": f"偏多研究 · {long_n}",
            "counts": counts,
        }
    if short_n > long_n and short_n > 0:
        return {
            "结论": "偏空研究",
            "note": f"总盘面偏空 {short_n} vs 偏多 {long_n}；观望 {watch_n}；情绪{sentiment_direction}",
            "label": f"偏空研究 · {short_n}",
            "counts": counts,
        }
    return {
        "结论": "观望",
        "note": f"观望 {watch_n}；多{long_n}/空{short_n}/卖波{sell_n}；情绪{sentiment_direction}{sentiment_conviction:.0f}%",
        "label": "观望",
        "counts": counts,
    }


# Bump when layout changes — visible in UI so stale Streamlit is obvious.
SENTIMENT_UI_BUILD = "2026-10-29c · PathA① / 波动② / 总盘面 / 明细③"


def render_sentiment_panel(root: Path) -> None:
    import streamlit as st

    st.subheader("情绪袖套 MDS+EHI（纸面对照）")
    st.caption(
        "MDS（席位流与价格同/背离）+ EHI（|净持仓|/OI）+ 软 P3。"
        "仅纸面对照，不改 Path-A 手数，不下实盘单。"
        "结论直接给多/空/震荡；把握%由 |P3| 与多空候选广度合成。"
    )
    st.caption(f"界面版本：`{SENTIMENT_UI_BUILD}`（若看不到①②③分区，说明还在跑旧进程）")
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

    # --- Table 1: Path-A 对照（原四列）---
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
                "代码": code,
                "品种": _variety_label(code),
                "情绪方向": sent,
                "Path-A持仓/日选": pa,
                "对照": align,
            }
        )
    if compare_rows:
        st.markdown("**① 与 Path-A 对照**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "品种": r["品种"],
                        "情绪方向": r["情绪方向"],
                        "Path-A持仓/日选": r["Path-A持仓/日选"],
                        "对照": r["对照"],
                    }
                    for r in compare_rows
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    # --- Table 2: 波动率引擎 ---
    vol_map: dict[str, dict] = {}
    vol_err: str | None = None
    vol_board: dict[str, Any] = {"ok": False, "rows": []}
    try:
        import importlib
        import sys

        sys.modules.pop("desk.vol_engine_panel", None)
        import desk.vol_engine_panel as _vep

        _vep = importlib.reload(_vep)
        st.divider()
        vol_board = _vep.render_vol_engine_section(
            root,
            button_key="vol_engine_refresh_sentiment",
            heading="**② 波动率引擎 V1**",
        )
        vol_map = _vep.vol_fields_by_code(root, board=vol_board)
    except Exception as exc:  # noqa: BLE001
        vol_err = f"{type(exc).__name__}: {exc}"
        st.warning(f"波动率引擎未加载：{vol_err}")

    # --- 总盘面结论（参考 Path-A 对照 + 波动盘面）---
    conv = float(verdict.get("conviction_pct") or 0)
    total_rows = []
    codes_union = sorted(
        {r["代码"] for r in compare_rows} | set(vol_map.keys())
    )
    align_by = {r["代码"]: r for r in compare_rows}
    for code in codes_union:
        base = align_by.get(code) or {
            "品种": _variety_label(code),
            "情绪方向": "多" if code in longs else ("空" if code in shorts else "—"),
            "Path-A持仓/日选": path_a.get(code) or "—",
            "对照": "—",
        }
        if base["对照"] == "—" and code not in align_by:
            se, pa = base["情绪方向"], base["Path-A持仓/日选"]
            if se in ("多", "空") and pa in ("多", "空"):
                base["对照"] = "同向" if se == pa else "冲突"
            elif se in ("多", "空"):
                base["对照"] = "仅情绪"
            elif pa in ("多", "空"):
                base["对照"] = "仅Path-A"
        vf = vol_map.get(code) or {}
        vol_c = str(vf.get("盘面结论") or "观望")
        tot = total_board_conclusion(
            align=str(base["对照"]),
            path_a=str(base["Path-A持仓/日选"]),
            sent=str(base["情绪方向"]),
            vol_conclusion=vol_c,
            sentiment_conviction=conv,
        )
        total_rows.append(
            {
                "品种": base["品种"],
                "对照": base["对照"],
                "波动盘面": vol_c,
                "总结论": tot["结论"],
                "说明": tot["note"],
            }
        )

    book = portfolio_total_verdict(
        total_rows,
        sentiment_direction=str(verdict.get("direction") or "—"),
        sentiment_conviction=conv,
    )
    st.markdown("### 总盘面结论")
    t0, t1, t2 = st.columns(3)
    t0.metric("总结论", book.get("结论") or "观望")
    t1.metric("情绪", verdict.get("label") or "—")
    t2.metric("对照品种数", len(total_rows))
    st.caption(
        str(book.get("note") or "")
        + " · 研究用，非下单指令"
        + (f" · 引擎异常：{vol_err}" if vol_err else "")
    )
    if total_rows:
        st.markdown("**总盘面明细**（Path-A对照 × 波动盘面）")
        st.dataframe(pd.DataFrame(total_rows), width="stretch", hide_index=True)

    # --- Table 3: 品种明细（情绪底层，放最后）---
    syms = snap.get("symbols") or []
    if syms:
        st.divider()
        st.markdown("**③ 品种明细**")
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
        st.json(
            {
                **snap,
                "verdict": verdict,
                "portfolio_total": book,
                "total_rows": total_rows,
            }
        )
