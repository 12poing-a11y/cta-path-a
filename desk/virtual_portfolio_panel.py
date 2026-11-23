# -*- coding: utf-8 -*-
"""Desk panel for VP Phase 1A — query + manual ops. Not a formal KPI page."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from virtual_portfolio.engine import (
    VpError,
    close_position,
    create_account,
    deposit,
    list_accounts,
    load_account_state,
    open_position,
    rebuild_account,
    withdraw,
)
from virtual_portfolio.ledger import load_events

DISCLAIMER = (
    "虚拟组合 Phase 1A：独立账户/账本；不接自动 CTA 信号；"
    "ACCOUNT_MODE=RESEARCH_ONLY · AUTO_OPEN/CLOSE/SIGNAL 默认 false；"
    "查询只读，投影重建须点按钮；不写入 paper_book。"
)


def render_virtual_portfolio_panel(root: Path) -> None:
    st.subheader("虚拟组合 · Phase 1A")
    st.caption(DISCLAIMER)

    accounts = list_accounts(root)
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 开户")
        new_id = st.text_input("account_id", key="vp_new_id")
        new_name = st.text_input("名称", key="vp_new_name", value="")
        init_cash = st.number_input("起始资金", min_value=0.0, value=200000.0, step=10000.0)
        if st.button("创建账户", key="vp_create"):
            try:
                create_account(root, new_id, name=new_name or None, initial_cash=float(init_cash))
                st.success(f"已创建 {new_id}")
                st.rerun()
            except (VpError, ValueError) as exc:
                st.error(str(exc))

    with col_b:
        st.markdown("#### 选择账户")
        if not accounts:
            st.info("暂无账户")
            return
        aid = st.selectbox("账户", accounts, key="vp_aid")

    if st.button("重建投影（显式）", key="vp_rebuild"):
        try:
            rebuild_account(root, aid, note="desk_manual_rebuild")
            st.success("投影已重建")
            st.rerun()
        except VpError as exc:
            st.error(str(exc))

    state = load_account_state(root, aid)  # read-only — no projection rewrite
    acct = state.get("account") or {}
    eq = state["equity"]
    if state.get("projections_missing"):
        st.warning("投影文件缺失：当前为内存计算结果；请点「重建投影」。")
    st.markdown("#### 运行状态")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "ACCOUNT_MODE": acct.get("ACCOUNT_MODE"),
                    "MARGIN_STATUS": acct.get("MARGIN_STATUS") or eq.get("MARGIN_STATUS"),
                    "AUTO_OPEN_ALLOWED": acct.get("AUTO_OPEN_ALLOWED"),
                    "AUTO_CLOSE_ALLOWED": acct.get("AUTO_CLOSE_ALLOWED"),
                    "SIGNAL_INGEST_ALLOWED": acct.get("SIGNAL_INGEST_ALLOWED"),
                    "read_only_load": state.get("read_only"),
                }
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.markdown("#### 权益")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "现金": eq.get("cash"),
                    "浮盈": eq.get("unrealized_pnl"),
                    "已实现": eq.get("realized_pnl"),
                    "权益": eq.get("equity"),
                    "保证金占用": eq.get("margin_used"),
                    "可用": eq.get("available"),
                    "保证金完整": eq.get("margin_complete"),
                    "flags": ",".join(eq.get("flags") or []),
                }
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("#### 持仓")
    pos = state.get("positions") or []
    st.dataframe(pd.DataFrame(pos) if pos else pd.DataFrame({"msg": ["空仓"]}), hide_index=True)

    st.markdown("#### 手工资金")
    c1, c2, c3 = st.columns(3)
    with c1:
        dep = st.number_input("入金", min_value=0.0, value=0.0, key="vp_dep")
        if st.button("入金", key="vp_dep_btn") and dep > 0:
            try:
                deposit(root, aid, dep, note="desk")
                st.rerun()
            except VpError as exc:
                st.error(str(exc))
    with c2:
        wd = st.number_input("出金", min_value=0.0, value=0.0, key="vp_wd")
        if st.button("出金", key="vp_wd_btn") and wd > 0:
            try:
                withdraw(root, aid, wd, note="desk")
                st.rerun()
            except VpError as exc:
                st.error(str(exc))

    st.markdown("#### 手工开平（fill_policy=next_open，自填开盘价）")
    oc1, oc2 = st.columns(2)
    with oc1:
        sym = st.text_input("品种", value="MA", key="vp_sym")
        side = st.selectbox("方向", ["long", "short"], key="vp_side")
        qty = st.number_input("手数", min_value=1, value=1, key="vp_qty")
        px = st.number_input("成交价", min_value=0.0, value=0.0, key="vp_px")
        asof = st.text_input("asof YYYY-MM-DD", key="vp_asof")
        if st.button("开仓", key="vp_open"):
            try:
                open_position(
                    root, aid, symbol=sym, side=side, qty=qty, price=px, asof=asof, note="desk"
                )
                st.rerun()
            except VpError as exc:
                st.error(str(exc))
    with oc2:
        c_sym = st.text_input("平仓品种", value=sym, key="vp_csym")
        c_qty = st.number_input("平仓手数", min_value=1, value=1, key="vp_cqty")
        c_px = st.number_input("平仓价", min_value=0.0, value=0.0, key="vp_cpx")
        c_asof = st.text_input("平仓 asof", value=asof, key="vp_casof")
        if st.button("平仓", key="vp_close"):
            try:
                close_position(
                    root, aid, symbol=c_sym, qty=c_qty, price=c_px, asof=c_asof, note="desk"
                )
                st.rerun()
            except VpError as exc:
                st.error(str(exc))

    st.markdown("#### Ledger 尾部")
    evs = load_events(root, aid)
    tail = evs[-30:]
    st.dataframe(pd.DataFrame(tail) if tail else pd.DataFrame(), hide_index=True)
