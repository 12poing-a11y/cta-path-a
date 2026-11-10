# -*- coding: utf-8 -*-
"""Desk panel: strategy × indicator ablation results (research only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

OUT_REL = Path("data") / "ablation" / "strategy_indicator_ablation_latest.json"
BLEND_REL = Path("data") / "ablation" / "strategy_blend_latest.json"

# English JSON keys → Chinese desk headers
_COL_ZH = {
    "strategy_id": "策略ID",
    "strategy_name": "策略",
    "variant": "变体",
    "variant_label": "变体说明",
    "ablated": "消融因子",
    "kept": "保留因子",
    "ret_pct": "收益%",
    "max_dd_pct": "最大回撤%",
    "calmar": "Calmar",
    "delta_ret_vs_full": "Δ收益vs完整",
    "delta_dd_vs_full": "Δ回撤vs完整",
    "n_trades": "交易笔数",
    "start": "起始",
    "end": "截止",
    "ok": "成功",
    "error": "错误",
    "elapsed_sec": "耗时秒",
    "note": "备注",
    "blend_id": "组合ID",
    "label": "组合",
    "weights_zh": "权重",
    "risk_note": "备注",
    "n_days": "共同交易日",
}


def _zh_frame(rows: list[dict[str, Any]] | pd.DataFrame, prefer: list[str] | None = None) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        df = rows.copy()
    else:
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
    if prefer:
        cols = [c for c in prefer if c in df.columns] + [
            c for c in df.columns if c not in prefer
        ]
        df = df[cols]
    return df.rename(columns={k: v for k, v in _COL_ZH.items() if k in df.columns})


def load_ablation(root: Path) -> dict[str, Any] | None:
    path = root / OUT_REL
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_blend(root: Path) -> dict[str, Any] | None:
    path = root / BLEND_REL
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _row_passes_quality(row: dict[str, Any], *, min_ret: float = 0.0, max_dd: float = 15.0) -> bool:
    if row.get("ok") is False:
        return False
    try:
        ret = float(row["ret_pct"])
        dd = float(row["max_dd_pct"])
    except (TypeError, ValueError, KeyError):
        return False
    return ret > min_ret and dd <= max_dd


def blend_rows_frame(payload: dict[str, Any]) -> pd.DataFrame:
    rows = [r for r in (payload.get("rows") or []) if _row_passes_quality(r)]
    if not rows:
        return pd.DataFrame()
    prefer = [
        "label",
        "weights_zh",
        "ret_pct",
        "max_dd_pct",
        "calmar",
        "n_days",
        "ok",
        "error",
        "risk_note",
    ]
    return _zh_frame(rows, prefer=prefer)


def rows_frame(payload: dict[str, Any]) -> pd.DataFrame:
    rows = [r for r in (payload.get("rows") or []) if _row_passes_quality(r)]
    if not rows:
        return pd.DataFrame()
    prefer = [
        "strategy_name",
        "variant_label",
        "ret_pct",
        "max_dd_pct",
        "calmar",
        "delta_ret_vs_full",
        "delta_dd_vs_full",
        "n_trades",
        "ok",
    ]
    raw = pd.DataFrame(rows)
    keep = [c for c in prefer if c in raw.columns] + [
        c for c in raw.columns if c not in prefer and c not in {"ablated", "error", "elapsed_sec"}
    ]
    return _zh_frame(raw[keep])


def render_blend_section(st, root: Path) -> None:
    """A capital-blend ranking (reads strategy_blend_latest.json)."""
    blend = load_blend(root)
    st.markdown("**策略资金组合（A·纸面）**")
    st.caption(
        "B→A：在消融候选曲线上扫离散权重；主排序 Calmar；观察袖套硬帽≤10%；"
        "全表剔除负收益或最大回撤>15%（及校验失败）的组合。"
        "运行：`python scripts/strategy_blend_grid.py`"
    )
    if not blend:
        st.info(f"尚无资金组合快照。请先跑脚本生成 `{BLEND_REL.as_posix()}`。")
        return
    st.caption(
        f"快照 {blend.get('asof') or '—'} · 共同交易日 {blend.get('n_common_days') or 0} · "
        f"曲线 {', '.join(blend.get('curves_loaded') or []) or '—'} · "
        f"{blend.get('disclaimer') or ''}"
    )
    b_ctx = blend.get("b_context") or {}
    if b_ctx.get("available"):
        st.caption(
            f"B 上下文：消融 {b_ctx.get('asof') or '—'} · mode={b_ctx.get('grid_mode') or '—'}"
        )
        top_b = b_ctx.get("top_pairs_by_ret") or []
        if top_b:
            with st.expander("B 消融收益 Top（只读）", expanded=False):
                st.dataframe(_zh_frame(top_b), width="stretch", hide_index=True)
    else:
        st.caption(f"B 上下文：{b_ctx.get('note') or '无消融快照'}")

    best_cal = blend.get("best_by_calmar") or []
    if best_cal:
        st.markdown("**Calmar 最高的资金组合**")
        st.dataframe(_zh_frame(best_cal), width="stretch", hide_index=True)
    best_ret = blend.get("best_by_ret") or []
    if best_ret:
        st.markdown("**收益最高的资金组合**")
        st.dataframe(_zh_frame(best_ret), width="stretch", hide_index=True)
    df = blend_rows_frame(blend)
    n_drop = int(blend.get("n_dropped") or 0)
    if not df.empty:
        st.markdown("**组合全表**")
        if n_drop:
            st.caption(f"已隐藏 {n_drop} 条不达标/失败组合")
        st.dataframe(df, width="stretch", hide_index=True)
    elif n_drop:
        st.caption(f"组合全表为空（已隐藏 {n_drop} 条不达标/失败组合）")
    try:
        from desk.blend_positions import render_blend_holdings

        st.divider()
        render_blend_holdings(st, root)
    except Exception as exc:  # soft-fail
        st.caption(f"最优组合持仓参考暂不可用：{exc}")


def render_ablation_panel(st, root: Path) -> None:
    """Render under 概览对比 — soft if missing."""
    payload = load_ablation(root)
    with st.expander("策略消融与资金组合（纸面 A+B）", expanded=False):
        render_blend_section(st, root)
        st.divider()
        st.markdown("**策略×指标消融（B·纸面）**")
        st.caption(
            "默认 full_grid：策略×指标组合全扫；也可用 `--mode ablation` 做单因子开关。"
            "运行：`python scripts/strategy_indicator_ablation.py`"
        )
        if not payload:
            st.info(f"尚无消融快照。请先跑脚本生成 `{OUT_REL.as_posix()}`。")
            return
        st.caption(
            f"快照 {payload.get('asof') or '—'} · mode={payload.get('grid_mode') or (payload.get('summary') or {}).get('grid_mode') or '—'} · "
            f"{payload.get('n_rows')} 行 · {payload.get('disclaimer') or ''}"
        )
        summary = payload.get("summary") or {}
        best = summary.get("best_full_strategies") or []
        if best:
            st.markdown("**完整策略横比（按收益）**")
            st.dataframe(_zh_frame(best), width="stretch", hide_index=True)
        top_ret = summary.get("top_pairs_by_ret") or []
        if top_ret:
            st.markdown("**收益最高的策略×指标组合**")
            st.dataframe(_zh_frame(top_ret), width="stretch", hide_index=True)
        top_cal = summary.get("top_pairs_by_calmar") or []
        if top_cal:
            st.markdown("**Calmar 最高的策略×指标组合**")
            st.dataframe(_zh_frame(top_cal), width="stretch", hide_index=True)
        valuable = summary.get("most_valuable_indicators") or []
        if valuable:
            st.markdown("**相对完整配置：关掉后掉得最多**")
            prefer = ["strategy_id", "variant_label", "delta_ret_vs_full", "delta_dd_vs_full", "note"]
            st.dataframe(
                _zh_frame(valuable, prefer=[c for c in prefer if c in (valuable[0] or {})]),
                width="stretch",
                hide_index=True,
            )
        weak = summary.get("redundant_or_harmful") or []
        if weak:
            st.markdown("**相对完整配置：关掉后几乎不变/变好**")
            prefer = ["strategy_id", "variant_label", "delta_ret_vs_full", "delta_dd_vs_full", "note"]
            st.dataframe(
                _zh_frame(weak, prefer=[c for c in prefer if c in (weak[0] or {})]),
                width="stretch",
                hide_index=True,
            )
        if summary.get("warrant_note"):
            st.caption(summary["warrant_note"])
        df = rows_frame(payload)
        if not df.empty:
            raw_n = len(payload.get("rows") or [])
            st.markdown("**全表**")
            st.caption(
                f"仅保留收益>0且最大回撤≤15%（{len(df)}/{raw_n}）；负收益或回撤不达标已隐藏"
            )
            st.dataframe(df, width="stretch", hide_index=True)
