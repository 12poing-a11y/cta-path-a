# -*- coding: utf-8 -*-
"""Desk panel: Volatility Engine V1 merged with Path-A / breakout / IV tags.

Paper research only (``live_trading=false``). Sell-vol is soft-annotate —
does not change Path-A futures entry (``entry_filter=seats``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from desk.loaders import format_variety_label, load_json, load_l1_report, load_universe

FOOTER = "研究建议，非交易指令。卖波仅标注，不改期货开仓。"
DEFAULT_CODES = ("CF", "SR", "MA", "TA", "RU", "AG", "RB")


def _side(label: str | None) -> str | None:
    text = str(label or "").strip()
    if text in ("多", "偏多", "long"):
        return "多"
    if text in ("空", "偏空", "short"):
        return "空"
    if text in ("震荡", "观望", "flat", "零"):
        return "震荡"
    return None


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_vol_engine_snapshot(root: Path) -> dict[str, Any] | None:
    path = Path(root) / "data" / "vol_engine_latest.json"
    payload = load_json(path)
    if isinstance(payload, dict) and payload.get("ok"):
        return payload
    return None


def _report_by_code(snap: dict[str, Any] | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in (snap or {}).get("reports") or []:
        if isinstance(row, dict) and row.get("code"):
            out[str(row["code"]).upper()] = row
    return out


def _final_action_map(root: Path) -> dict[str, dict]:
    """Reuse final-signal board for TP/SL alerts (fast path)."""
    try:
        from desk.final_signal import build_final_signal_board

        board = build_final_signal_board(root, compute_decisions=True)
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict] = {}
    for bucket in ("primary", "other"):
        for row in board.get(bucket) or []:
            if isinstance(row, dict) and row.get("代码"):
                out[str(row["代码"]).upper()] = row
    return out


def board_conclusion(
    *,
    final_action: str | None,
    matrix_tag: str | None,
    false_breakout: bool,
    path_a_selected: bool,
    path_a_side: str | None,
    breakout_side: int | None,
    buy_vol: bool,
    sell_vol: bool,
    trend_side: int | None,
    sentiment_tier: str | None = None,
) -> dict[str, Any]:
    """Paper board priority:

    1. TP/SL alerts from final signal
    1b. sentiment opposed_hard → 观望
    2. no_trade / false breakout → 观望
    3. Path-A day-pick + same-side breakout + buy_vol/direction → 偏多/偏空
    4. sell_vol only, no Path-A conflict → 波动率卖方研究 (annotate)
    """
    action = str(final_action or "").strip()
    if action in ("止盈预警", "止损预警"):
        return {
            "结论": action,
            "优先级": 1,
            "note": "持仓止盈/止损预警优先",
        }

    stier = str(sentiment_tier or "")
    if stier == "opposed_hard":
        return {
            "结论": "观望",
            "优先级": 1,
            "note": "情绪硬反向(把握≥60)否决追方向/买波",
            "sentiment_tier": stier,
        }

    tag = str(matrix_tag or "no_trade")
    if tag == "no_trade" or false_breakout:
        note = "空仓标签或假突破嫌疑"
        if stier == "opposed_soft":
            note = "情绪软反向+空仓/假突破 → 观望"
        return {
            "结论": "观望",
            "优先级": 2,
            "note": note,
            "sentiment_tier": stier or None,
        }

    bo = int(breakout_side or 0)
    pa = _side(path_a_side)
    same_dir = (
        path_a_selected
        and pa in ("多", "空")
        and bo != 0
        and ((pa == "多" and bo > 0) or (pa == "空" and bo < 0))
    )
    if same_dir and (buy_vol or (trend_side or 0) != 0):
        return {
            "结论": "偏多研究" if pa == "多" else "偏空研究",
            "优先级": 3,
            "note": "日选+同向突破+买波/方向标签"
            + ("；情绪同向" if stier == "aligned" else ""),
            "sentiment_tier": stier or None,
        }

    if sell_vol and tag == "sell_vol_credit_spread":
        note = "卖波标注；不改期货开仓"
        if stier == "extreme_crowd":
            note = "情绪拥挤+卖波条件 → 波动率卖方研究（仅标注）"
        return {
            "结论": "波动率卖方研究",
            "优先级": 4,
            "note": note,
            "annotate_only": True,
            "sentiment_tier": stier or None,
        }

    if buy_vol:
        side = pa or ("多" if (trend_side or 0) > 0 else "空" if (trend_side or 0) < 0 else None)
        if side in ("多", "空"):
            return {
                "结论": "偏多研究" if side == "多" else "偏空研究",
                "优先级": 3,
                "note": "买波/方向期权研究",
                "sentiment_tier": stier or None,
            }

    if tag == "calendar_candidate":
        return {
            "结论": "日历价差研究",
            "优先级": 4,
            "note": "近远月IV结构候选",
            "annotate_only": True,
            "sentiment_tier": stier or None,
        }

    return {
        "结论": "观望",
        "优先级": 2,
        "note": "条件未齐",
        "sentiment_tier": stier or None,
    }


def build_vol_engine_board(
    root: Path,
    *,
    codes: list[str] | None = None,
    snap: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
    recompute: bool = False,
) -> dict[str, Any]:
    """Per-code rows: Path-A + breakout/IV + vol engine + board conclusion."""
    root = Path(root)
    codes = [c.upper() for c in (codes or list(DEFAULT_CODES))]
    if snap is None and not recompute:
        snap = load_vol_engine_snapshot(root)
    if recompute or snap is None:
        try:
            from vol_engine import run_universe

            snap = run_universe(
                root,
                codes,
                write_data=True,
                write_oos=False,
                fetch_calendar=False,
            )
        except Exception as exc:  # noqa: BLE001
            snap = load_vol_engine_snapshot(root) or {
                "ok": False,
                "error": f"{type(exc).__name__}:{exc}",
            }
    if snap is None:
        snap = {"ok": False, "reports": []}

    report = report if report is not None else (load_l1_report(root) or {})
    sig_map: dict[str, dict] = {}
    for row in report.get("signals") or []:
        if isinstance(row, dict) and row.get("code"):
            sig_map[str(row["code"]).upper()] = row

    names: dict[str, str] = {}
    for row in (load_universe(root) or {}).get("symbols") or []:
        if isinstance(row, dict) and row.get("code"):
            names[str(row["code"]).upper()] = str(row.get("name") or "")

    final_map = _final_action_map(root)
    by_code = _report_by_code(snap)
    rows: list[dict[str, Any]] = []

    for code in codes:
        pack = by_code.get(code) or {}
        sig = sig_map.get(code) or {}
        final = final_map.get(code) or {}
        matrix = pack.get("matrix") or {}
        trend = pack.get("trend") or {}
        bo = pack.get("breakout") or {}
        state = pack.get("vol_state") or {}
        pricing = pack.get("vol_pricing") or {}

        pa_side = _side(sig.get("direction"))
        pa_sel = bool(sig.get("selected"))
        lots = _num(sig.get("lots")) if pa_sel else None
        book_label = str(final.get("模拟仓") or ("日选" if pa_sel else "—"))

        bo_side = int(bo.get("side") or 0)
        if bo.get("stale"):
            bo_label = "无（非当日）"
        elif bo_side > 0:
            bo_label = f"上破/{bo.get('iv_tag') or '—'}"
        elif bo_side < 0:
            bo_label = f"下破/{bo.get('iv_tag') or '—'}"
        else:
            bo_label = f"无/{bo.get('iv_tag') or '—'}"

        sent = pack.get("sentiment") or {}
        conclusion = board_conclusion(
            final_action=str(final.get("最终动作") or ""),
            matrix_tag=str(matrix.get("tag") or ""),
            false_breakout=bool(matrix.get("false_breakout")),
            path_a_selected=pa_sel,
            path_a_side=pa_side,
            breakout_side=0 if bo.get("stale") else bo_side,
            buy_vol=bool(matrix.get("buy_vol")),
            sell_vol=bool(matrix.get("sell_vol")),
            trend_side=int(trend.get("side") or 0),
            sentiment_tier=str(
                matrix.get("sentiment_tier") or sent.get("tier") or ""
            ),
        )

        rows.append(
            {
                "代码": code,
                "品种": format_variety_label(code, names.get(code, ""), root=root),
                "Path-A": (
                    f"{'日选' if pa_sel else '信号'}{pa_side or '—'}"
                    + (f"/{int(lots)}手" if lots is not None else "")
                ),
                "模拟仓": book_label,
                "突破": bo_label,
                "情绪分档": sent.get("label") or matrix.get("sentiment_tier") or "—",
                "波动状态": f"{state.get('label') or '—'}({state.get('score')})",
                "定价": f"{pricing.get('label') or '—'}({pricing.get('score')})",
                "引擎标签": matrix.get("tag") or "—",
                "理由": matrix.get("reason") or "—",
                "盘面结论": conclusion.get("结论"),
                "盘面说明": conclusion.get("note"),
                "最终动作": final.get("最终动作") or "—",
                "_pack": pack,
                "_conclusion": conclusion,
            }
        )

    return {
        "ok": bool(snap.get("ok", True)),
        "live_trading": False,
        "entry_filter_unchanged": "seats",
        "codes": codes,
        "rows": rows,
        "snap": snap,
        "note": FOOTER,
    }


def persist_board_overlay(root: Path, board: dict[str, Any]) -> Path:
    """Merge board conclusions into data/vol_engine_latest.json."""
    root = Path(root)
    path = root / "data" / "vol_engine_latest.json"
    base = load_json(path) if path.is_file() else {}
    if not isinstance(base, dict):
        base = {}
    overlay = {
        str(r["代码"]): {
            "盘面结论": r.get("盘面结论"),
            "盘面说明": r.get("盘面说明"),
            "引擎标签": r.get("引擎标签"),
            "最终动作": r.get("最终动作"),
        }
        for r in board.get("rows") or []
        if r.get("代码")
    }
    base["ok"] = True
    base["live_trading"] = False
    base["desk_board"] = overlay
    base["desk_note"] = FOOTER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def vol_fields_by_code(root: Path, board: dict[str, Any] | None = None) -> dict[str, dict]:
    """Map CODE → vol display fields for joining Path-A / sentiment tables."""
    if board is None:
        board = build_vol_engine_board(root, recompute=False)
    out: dict[str, dict] = {}
    for row in board.get("rows") or []:
        code = str(row.get("代码") or "").upper()
        if not code:
            continue
        out[code] = {
            "情绪分档": row.get("情绪分档") or "—",
            "波动状态": row.get("波动状态") or "—",
            "定价": row.get("定价") or "—",
            "引擎标签": row.get("引擎标签") or "—",
            "盘面结论": row.get("盘面结论") or "—",
            "突破": row.get("突破") or "—",
        }
    return out


def render_vol_engine_section(
    root: Path,
    *,
    recompute: bool = False,
    button_key: str = "vol_engine_refresh",
    heading: str = "#### 波动率引擎 V1",
) -> dict[str, Any]:
    """Streamlit vol board (default: embed on 情绪页). No separate 代码 column."""
    import pandas as pd
    import streamlit as st

    st.markdown(heading)
    st.caption(FOOTER + " · live_trading=否 · entry_filter=seats 不变")

    col_a, col_b = st.columns([1, 3])
    with col_a:
        do_refresh = st.button("刷新引擎", key=button_key)
    with col_b:
        st.caption("默认读 data/vol_engine_latest.json；刷新会重算并写回。")

    with st.spinner("合并 Path-A / 突破 / IV / 波动引擎…"):
        board = build_vol_engine_board(
            root,
            recompute=bool(recompute or do_refresh),
        )
        if board.get("ok"):
            persist_board_overlay(root, board)

    rows = board.get("rows") or []
    if not rows:
        st.info("暂无波动引擎结果。可运行 `python vol_engine.py` 或点刷新。")
        return board

    # 品种 already carries code+name; omit 代码.
    show_cols = [
        "品种",
        "Path-A",
        "模拟仓",
        "突破",
        "情绪分档",
        "波动状态",
        "定价",
        "引擎标签",
        "盘面结论",
        "理由",
    ]
    frame = pd.DataFrame([{k: r.get(k) for k in show_cols} for r in rows])
    st.dataframe(frame, width="stretch", hide_index=True)
    st.caption(FOOTER)
    return board
