# -*- coding: utf-8 -*-
"""Full statistical assessment for the regime tab.

Merges Path-A direction buckets, HMM, model hit scores, decision card,
equity-index timing, and strategy-library scoreboard into one expandable
research summary. Not a live order.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from desk.loaders import load_json
from desk.scoreboard import composite_score, scoreboard_rows
from equity_timing import load_spec, pack_day, suggested_weight

GREEN = "#14804a"
RED = "#d1242f"


def _num(value: Any) -> float | None:
    if value is None or value is False:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _side_points(label: str) -> float:
    text = str(label or "")
    if text in ("多", "偏多"):
        return 1.0
    if text in ("空", "偏空"):
        return -1.0
    return 0.0


def equity_timing_snapshot(root: Path) -> dict[str, Any]:
    """Latest equity timing rows + mean suggested weight (-1..1)."""
    spec = load_spec(root / "external" / "equity_timing_spec.json")
    latest = load_json(root / "external" / "equity_timing_latest.json") or {}
    name_by = {t["code"]: t["name"] for t in spec.get("targets") or []}
    rows: list[dict[str, Any]] = []
    weights: list[float] = []
    for code, payload in (latest.get("targets") or {}).items():
        if not isinstance(payload, dict):
            continue
        cats = payload.get("categories") or {}
        comp = payload.get("composite")
        if cats and comp is None:
            packed = pack_day(asof=str(latest.get("asof") or ""), target=code, categories=cats)
            comp = packed.get("composite")
            w = {
                "weight": packed.get("suggested_weight"),
                "label": packed.get("suggested_weight_label"),
                "bucket": packed.get("bucket"),
            }
        else:
            w = suggested_weight(comp if comp is not None else None)
        if w.get("weight") is not None:
            weights.append(float(w["weight"]))
        rows.append(
            {
                "指数": name_by.get(code, code),
                "代码": code,
                "合成信号": comp,
                "建议权重": w.get("label"),
                "权重": w.get("weight"),
                "分桶": w.get("bucket"),
            }
        )
    mean_w = sum(weights) / len(weights) if weights else None
    if mean_w is None:
        bias = "无信号"
    elif mean_w > 0.25:
        bias = "偏多"
    elif mean_w < -0.25:
        bias = "偏空"
    else:
        bias = "中性"
    return {
        "asof": latest.get("asof"),
        "rows": rows,
        "mean_weight": mean_w,
        "bias": bias,
        "n_filled": sum(1 for r in rows if r.get("合成信号") is not None or r.get("权重") is not None),
        "spec": spec,
    }


def strategy_library_stats(root: Path) -> dict[str, Any]:
    rows = scoreboard_rows(root)
    scored = [r for r in rows if isinstance(r.get("评分"), (int, float))]
    top = scored[:5]
    mean_score = (
        sum(float(r["评分"]) for r in scored) / len(scored) if scored else None
    )
    return {
        "rows": rows,
        "scored": scored,
        "top": top,
        "n_scored": len(scored),
        "n_total": len(rows),
        "mean_score": round(mean_score, 1) if mean_score is not None else None,
        "best": scored[0] if scored else None,
    }


def build_full_assessment(
    root: Path,
    code: str,
    *,
    pack: dict[str, Any],
    report: dict | None,
    regime_row: dict[str, Any] | None,
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    """Aggregate all desk research layers for one symbol + global tracks."""
    ensemble = pack.get("ensemble") or {}
    hmm = pack.get("hmm") or {}
    models = list(pack.get("models") or [])
    ens_dir = str(ensemble.get("direction") or "样本不足")
    hmm_label = str(hmm.get("latest") or "无足够日线") if hmm.get("ok") else "无足够日线"
    decision = decision or {}
    conclusion = str(decision.get("结论") or "观望")
    conviction = str(decision.get("把握") or "低")

    long_b = _num((regime_row or {}).get("多"))
    short_b = _num((regime_row or {}).get("空"))
    chop_b = _num((regime_row or {}).get("震荡"))
    signed = _num((regime_row or {}).get("原评分"))

    eq = equity_timing_snapshot(root)
    lib = strategy_library_stats(root)

    # Layer weights: R2 main axis, HMM demoted (HMM×R2 OOS A-gate fail).
    layer_w = {
        "方向三桶": 1.2,
        "趋势R2": 1.8,
        "HMM": 0.25,
        "模型投票": 1.5,
        "决策卡": 1.3,
        "股指择时": 0.8,
        "策略库均分": 0.7,
    }
    try:
        from desk.regime_board import load_vote_weights

        cw = (load_vote_weights(root).get("raw") or {}).get("composite_layer_weights") or {}
        if isinstance(cw, dict):
            for k, v in cw.items():
                try:
                    layer_w[str(k)] = float(v)
                except (TypeError, ValueError):
                    continue
    except Exception:
        pass

    r2_row = next((m for m in models if m.get("模型") == "趋势R2"), None)
    r2_dir = str((r2_row or {}).get("最新方向") or "样本不足")
    r2_score = (r2_row or {}).get("评分")

    # Layer votes then map to 综合分 0–100 research index.
    layers = [
        {"层": "方向三桶", "方向": (
            "多" if (long_b or 0) > (short_b or 0) and (long_b or 0) >= (chop_b or 0)
            else "空" if (short_b or 0) > (long_b or 0) and (short_b or 0) >= (chop_b or 0)
            else "震荡" if regime_row else "样本不足"
        ), "分": signed, "权重": layer_w["方向三桶"]},
        {
            "层": "趋势R2",
            "方向": r2_dir if r2_dir in ("多", "空", "震荡") else "样本不足",
            "分": r2_score if isinstance(r2_score, (int, float)) else None,
            "权重": layer_w["趋势R2"] if r2_row else 0.0,
        },
        {
            "层": "HMM",
            "方向": hmm_label if hmm_label in ("偏多", "偏空", "震荡") else "样本不足",
            "分": None,
            "权重": layer_w["HMM"],
        },
        {"层": "模型投票", "方向": ens_dir, "分": None, "权重": layer_w["模型投票"]},
        {
            "层": "决策卡",
            "方向": conclusion.replace("偏", "") if conclusion.startswith("偏") else conclusion,
            "分": None,
            "权重": layer_w["决策卡"],
        },
        {
            "层": "股指择时",
            "方向": eq["bias"],
            "分": (eq["mean_weight"] * 50.0) if eq["mean_weight"] is not None else None,
            "权重": (layer_w["股指择时"] if eq["n_filled"] else 0.0),
        },
        {
            "层": "策略库均分",
            "方向": (
                "偏多" if (lib["mean_score"] or 0) >= 60
                else "偏空" if (lib["mean_score"] or 0) < 40 and lib["mean_score"] is not None
                else "中性" if lib["mean_score"] is not None
                else "无"
            ),
            "分": lib["mean_score"],
            "权重": (layer_w["策略库均分"] if lib["n_scored"] else 0.0),
        },
    ]

    # Normalize HMM/decision labels to 多/空/震荡
    for row in layers:
        d = str(row["方向"] or "")
        if d == "偏多":
            row["方向"] = "多"
        elif d == "偏空":
            row["方向"] = "空"
        elif d in ("观望", "中性", "无信号", "无"):
            row["方向"] = "震荡" if d != "无" else "样本不足"

    vote = {"多": 0.0, "空": 0.0, "震荡": 0.0}
    used = 0
    for row in layers:
        w = float(row.get("权重") or 0)
        if w <= 0:
            continue
        side = str(row.get("方向") or "")
        if side not in vote:
            continue
        vote[side] += w
        used += 1
    if used == 0:
        overall = "样本不足"
    else:
        top = max(vote.values())
        winners = [k for k, v in vote.items() if abs(v - top) < 1e-9]
        overall = winners[0] if len(winners) == 1 else "震荡"

    # Research score 0–100 from layer agreement + library mean + |signed|
    agree = vote.get(overall, 0.0) / max(sum(vote.values()), 1e-9) if overall in vote else 0.0
    base = 40.0 + 40.0 * agree
    if signed is not None:
        base += max(-10.0, min(10.0, abs(signed) / 10.0))
    if lib["mean_score"] is not None:
        base = 0.7 * base + 0.3 * float(lib["mean_score"])
    full_score = round(max(0.0, min(100.0, base)), 1)

    model_ok = [m for m in models if isinstance(m.get("评分"), (int, float))]

    # Soft attach HMM multi-factor / combo summary (same foundation as regime_factor_eval).
    factor_eval: dict[str, Any] | None = None
    try:
        from desk.regime_factor_eval import build_regime_factor_assessment

        factor_eval = build_regime_factor_assessment(root, code)
    except Exception:
        factor_eval = None

    return {
        "code": code,
        "root": str(root),
        "overall": overall,
        "full_score": full_score,
        "conviction": conviction,
        "conclusion": conclusion,
        "vote": vote,
        "layers": layers,
        "regime": {
            "多": long_b,
            "空": short_b,
            "震荡": chop_b,
            "原评分": signed,
        },
        "hmm": hmm_label,
        "ensemble": ens_dir,
        "models": model_ok,
        "equity": eq,
        "library": lib,
        "factor_eval": factor_eval,
        "notes": list(pack.get("notes") or []),
    }


def _equity_brief(eq: dict[str, Any]) -> tuple[str, str] | None:
    """Return (metric_value, caption). None when no index signal is on file."""
    if not eq.get("n_filled"):
        return None
    bias = str(eq.get("bias") or "—")
    mean_w = eq.get("mean_weight")
    mean_txt = f"{mean_w:+.0%}" if isinstance(mean_w, (int, float)) else "—"
    bits = []
    for row in eq.get("rows") or []:
        name = str(row.get("指数") or row.get("代码") or "")
        label = row.get("建议权重")
        comp = row.get("合成信号")
        if label in (None, "—") and comp is None:
            continue
        if label and label != "—":
            bits.append(f"{name} {label}")
        elif comp is not None:
            bits.append(f"{name} 合成{float(comp):+.2f}")
    detail = " · ".join(bits) if bits else f"均权 {mean_txt}"
    return f"{bias}（均权 {mean_txt}）", f"股指 {detail}"


def render_full_assessment(
    assessment: dict[str, Any],
    *,
    expanded: bool = True,
    root: Path | None = None,
) -> None:
    st.markdown("**综合评估**")
    st.caption(
        "合并方向三桶、HMM、模型投票、决策卡、股指择时与策略库评分板，"
        "得到研究用综合方向与 0–100 全面统计分；不是下单指令。"
        "决策卡已含升贴水旁路与多维波动旁路（高波扩张时可降观望）。"
        "因子实验室 Gate 只读展示，不计入本页投票、不改开仓。"
    )
    eq = assessment.get("equity") or {}
    brief = _equity_brief(eq)
    if brief:
        eq_value, eq_caption = brief
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("综合方向", assessment.get("overall") or "—")
        c2.metric("全面统计分", assessment.get("full_score"))
        c3.metric("决策结论", assessment.get("conclusion") or "—")
        c4.metric("把握", assessment.get("conviction") or "—")
        c5.metric("股指", eq_value)
        extra = eq_caption
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("综合方向", assessment.get("overall") or "—")
        c2.metric("全面统计分", assessment.get("full_score"))
        c3.metric("决策结论", assessment.get("conclusion") or "—")
        c4.metric("把握", assessment.get("conviction") or "—")
        extra = ""
    vote = assessment.get("vote") or {}
    st.caption(
        f"层投票权重：多 {float(vote.get('多') or 0):.1f} / "
        f"空 {float(vote.get('空') or 0):.1f} / "
        f"震荡 {float(vote.get('震荡') or 0):.1f}"
        + (f"。{extra}。" if extra else "。")
    )

    with st.expander("展开 · 分层依据与全面统计", expanded=expanded):
        layers = pd.DataFrame(assessment.get("layers") or [])
        if not layers.empty:
            st.markdown("**分层投票**")
            st.dataframe(layers, width="stretch", hide_index=True)

        reg = assessment.get("regime") or {}
        hmm = assessment.get("hmm")
        ens = assessment.get("ensemble")
        m1, m2, m3 = st.columns(3)
        m1.metric("方向原评分", f"{reg.get('原评分'):+.1f}" if reg.get("原评分") is not None else "—")
        m2.metric("HMM", str(hmm or "—"))
        m3.metric("模型投票", str(ens or "—"))
        if any(reg.get(k) is not None for k in ("多", "空", "震荡")):
            st.caption(
                f"三桶 多 {reg.get('多')} / 空 {reg.get('空')} / 震荡 {reg.get('震荡')}"
            )

        models = assessment.get("models") or []
        if models:
            st.markdown("**模型命中评分（计入投票）**")
            show = pd.DataFrame(models)
            prefer = [c for c in ("模型", "最新方向", "评分", "命中率", "均收益", "样本天数") if c in show.columns]
            st.dataframe(show[prefer] if prefer else show, width="stretch", hide_index=True)

        eq = assessment.get("equity") or {}
        if eq.get("n_filled"):
            st.markdown("**股指择时（计入综合）**")
            st.caption(
                f"asof={eq.get('asof') or '—'} · 倾向 {eq.get('bias')} · "
                f"均权 {eq.get('mean_weight')}"
            )
            st.dataframe(pd.DataFrame(eq.get("rows") or []), width="stretch", hide_index=True)

        lib = assessment.get("library") or {}
        st.markdown("**策略评分（并入本页）**")
        st.caption(
            "只列有评分的策略。把握：评分≥65、夏普≥1.4、交易胜率≥45%、Calmar≥1.2 中满足 3 项为高，"
            "满足 1 项或评分≥50 为中，否则为低。胜率只展示回测里已有的字段；上涨日占比来自权益曲线。"
        )
        scored = lib.get("scored") or []
        if scored:
            board = pd.DataFrame(scored)
            cols = [
                c
                for c in (
                    "评分",
                    "把握",
                    "策略",
                    "交易胜率%",
                    "方向胜率%",
                    "上涨日占比%",
                    "盈亏平衡胜率%",
                    "年化%",
                    "夏普",
                    "Calmar",
                    "最大回撤%",
                    "平仓笔数",
                    "类型",
                )
                if c in board.columns
            ]
            st.dataframe(board[cols], width="stretch", hide_index=True)
            high = board[board["把握"] == "高"] if "把握" in board.columns else board.iloc[0:0]
            if not high.empty:
                names = "、".join(str(x) for x in high["策略"].head(4))
                st.caption(f"把握为高：{names}")
            try:
                chart = board.set_index("策略")["评分"].head(12)
                st.bar_chart(chart)
            except Exception:
                pass
        else:
            st.warning("没有带评分的策略。")

        fe = assessment.get("factor_eval") or {}
        if fe.get("ok"):
            st.markdown("**HMM 多因子摘要**（详见下方「HMM 多因子 · 组合 · 事件评估」）")
            counts = fe.get("regime_counts") or {}
            st.caption(
                f"HMM→{fe.get('hmm', {}).get('latest') or '—'} · "
                f"日数 多 {counts.get('多', 0)} / 空 {counts.get('空', 0)} / "
                f"震荡 {counts.get('震荡', 0)} · "
                f"因子 {len(fe.get('factors') or [])} · "
                f"组合 {len(fe.get('combos') or [])}"
            )
            if any(True for c in (fe.get("combos") or []) if c.get("优势状态")):
                bits = [
                    f"{c.get('因子')}→优势{c.get('优势状态')}"
                    for c in (fe.get("combos") or [])
                ]
                st.caption("组合优势状态：" + "；".join(bits))

        desk_root = root
        if desk_root is None:
            desk_root = Path(str(assessment.get("root") or Path(__file__).resolve().parents[1]))
        from desk.lab_panel import render_lab_gate_panel

        render_lab_gate_panel(Path(desk_root), compact=True, widget_ns="regime_assess")

        for note in assessment.get("notes") or []:
            st.caption(note)

    st.caption("研究观察，不构成交易建议。")
