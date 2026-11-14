# -*- coding: utf-8 -*-
"""Desk panel: 品类×策略影子胜率（Research only · 不计分）."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from research.shadow_perf import HORIZONS, MIN_SAMPLE, load_ledger, load_summary

LABEL = "影子归因·品类胜率·不计分"


def _zh_bucket_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    rename = {
        "strategy_label": "策略",
        "bucket": "品类",
        "code": "品种",
        "name": "名称",
        "n": "笔数",
        "win_rate_pct": "胜率%",
        "avg_ret_pct": "平均收益%",
        "avg_r": "平均R",
        "enough": "样本充足",
        "horizon": "前瞻日",
        "strategy_id": "策略ID",
    }
    prefer = [
        "strategy_label",
        "bucket",
        "code",
        "name",
        "n",
        "win_rate_pct",
        "avg_ret_pct",
        "avg_r",
        "enough",
        "horizon",
    ]
    cols = [c for c in prefer if c in df.columns] + [
        c for c in df.columns if c not in prefer and c in rename
    ]
    out = df[cols].rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "样本充足" in out.columns:
        out["样本充足"] = out["样本充足"].map(lambda x: "是" if x else "否（仅展示）")
    return out


def render_shadow_perf_panel(root: Path) -> dict[str, Any] | None:
    import streamlit as st

    st.caption(
        f"【{LABEL}】每日从 L1 同向信号 / 路径A入选 / 情绪影子抽候选，"
        f"T+{'/'.join(str(h) for h in HORIZONS)} 用连续合约收盘回填。"
        f"单格样本 <{MIN_SAMPLE} 只展示、不下结论；不进 Path-A、不改 paper_book。"
    )
    pack = load_summary(root)
    if not pack:
        st.info(
            "尚无影子归因快照。日更 soft 步骤会写 `data/shadow_perf/`，"
            "也可本地：`python scripts/run_shadow_perf.py --backfill-history`。"
        )
        return None

    st.markdown(
        f"**asof** `{pack.get('asof') or '—'}` · "
        f"台账 {pack.get('n_ledger') or 0} 行 · "
        f"更新 `{pack.get('updated_at') or '—'}`"
    )
    if pack.get("live_trading"):
        st.error("live_trading=true，与影子口径不符，待核。")

    summaries = pack.get("summaries") or {}
    h_opts = [int(h) for h in (pack.get("horizons") or HORIZONS)]
    horizon = st.selectbox("前瞻交易日", h_opts, index=0, key="shadow_perf_horizon")
    summary = summaries.get(str(horizon)) or pack.get("summary") or {}
    if int(summary.get("horizon") or 0) != int(horizon):
        # fallback recompute from ledger if summaries missing this h
        from research.shadow_perf import aggregate_summary

        summary = aggregate_summary(load_ledger(root), horizon=int(horizon))

    st.caption(summary.get("disclaimer") or pack.get("disclaimer") or "")

    by_bucket = summary.get("by_bucket") or []
    by_strategy = summary.get("by_strategy") or []
    by_code = summary.get("by_code") or []

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**按策略**")
        df_s = _zh_bucket_frame(by_strategy)
        if df_s.empty:
            st.caption("无已回填样本。")
        else:
            st.dataframe(df_s, width="stretch", hide_index=True)
    with c2:
        st.markdown("**按品类×策略**")
        df_b = _zh_bucket_frame(by_bucket)
        if df_b.empty:
            st.caption("无已回填样本。")
        else:
            # Grey hint: not enough sample rows first
            st.dataframe(df_b, width="stretch", hide_index=True)

    enough_n = sum(1 for r in by_bucket if r.get("enough"))
    st.caption(
        f"品类×策略格子：{len(by_bucket)} · 样本充足（≥{MIN_SAMPLE}）：{enough_n}"
    )

    with st.expander("按品种×策略明细", expanded=False):
        df_c = _zh_bucket_frame(by_code)
        if df_c.empty:
            st.caption("无明细。")
        else:
            st.dataframe(df_c, width="stretch", hide_index=True)

    with st.expander("台账最近行", expanded=False):
        ledger = load_ledger(root)
        recent = list(reversed(ledger[-80:]))
        if not recent:
            st.caption("台账空。")
        else:
            view = []
            for r in recent:
                fwd1 = (r.get("fwd") or {}).get("1") or {}
                view.append(
                    {
                        "日期": r.get("asof"),
                        "策略": r.get("strategy_label") or r.get("strategy_id"),
                        "品种": r.get("code"),
                        "品类": r.get("bucket"),
                        "方向": "多" if int(r.get("side") or 0) > 0 else "空",
                        "状态": r.get("status"),
                        "T+1收益%": fwd1.get("ret_pct"),
                        "T+1命中": fwd1.get("hit"),
                        "T+1 R": fwd1.get("r_mult"),
                    }
                )
            st.dataframe(pd.DataFrame(view), width="stretch", hide_index=True)

    return pack
