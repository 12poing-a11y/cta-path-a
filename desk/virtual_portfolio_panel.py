# -*- coding: utf-8 -*-
"""Desk panel for VP Phase 1A — query + manual ops. Not a formal KPI page."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
from virtual_portfolio.signal_inbox import (
    ingest_l1_to_inbox,
    list_inbox_asofs,
    load_inbox_asof,
    load_inbox_events,
    load_inbox_latest,
    load_vp_runtime,
    set_signal_read_allowed,
)

DISCLAIMER = (
    "虚拟组合 Phase 1A+1B-0：独立账户/账本；"
    "1B-0 仅只读收 L1 到收件箱，不自动下单；"
    "账户模式=仅研究 · 自动开/平/信号接入默认关闭；"
    "查询只读，投影重建须点按钮；不写入正式纸面模拟仓。"
)

# Display-only column renames (storage keys stay English).
_COL_ZH: dict[str, str] = {
    "ACCOUNT_MODE": "账户模式",
    "MARGIN_STATUS": "保证金状态",
    "AUTO_OPEN_ALLOWED": "允许自动开仓",
    "AUTO_CLOSE_ALLOWED": "允许自动平仓",
    "SIGNAL_INGEST_ALLOWED": "允许信号接入(下单管线)",
    "SIGNAL_READ_ALLOWED": "允许只读收信号",
    "read_only_load": "只读加载",
    "cash": "现金",
    "unrealized_pnl": "浮盈",
    "realized_pnl": "已实现盈亏",
    "equity": "权益",
    "margin_used": "保证金占用",
    "available": "可用资金",
    "margin_complete": "保证金完整",
    "flags": "标记",
    "symbol": "品种",
    "side": "方向",
    "qty": "手数",
    "avg_price": "均价",
    "opened_asof": "开仓日期",
    "margin_rate": "保证金率",
    "margin_tier": "保证金档",
    "lots": "批次",
    "account_id": "账户ID",
    "kind": "类型",
    "event_id": "事件ID",
    "client_event_id": "客户端事件ID",
    "price": "价格",
    "fee": "手续费",
    "fee_close_today": "平今手续费",
    "asof": "业务日",
    "source": "来源",
    "note": "备注",
    "recorded_at": "记录时间",
    "schema": "模式",
    "amount": "金额",
    "deduped": "已去重",
    "msg": "说明",
}

_SIDE_ZH = {"long": "多", "short": "空"}
_KIND_ZH = {
    "open": "开仓",
    "close": "平仓",
    "deposit": "入金",
    "withdraw": "出金",
    "create": "开户",
    "mark": "盯市",
}


def _df_zh(rows: list[dict[str, Any]] | dict[str, Any]) -> pd.DataFrame:
    if isinstance(rows, dict):
        rows = [rows]
    if not rows:
        return pd.DataFrame()
    out: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for k, v in row.items():
            if k == "lots":
                continue  # nested; skip in flat table
            zh = _COL_ZH.get(str(k), str(k))
            if k == "side" and isinstance(v, str):
                v = _SIDE_ZH.get(v, v)
            elif k == "kind" and isinstance(v, str):
                v = _KIND_ZH.get(v, v)
            elif isinstance(v, bool):
                v = "是" if v else "否"
            item[zh] = v
        out.append(item)
    return pd.DataFrame(out)


def _render_signal_inbox(root: Path) -> None:
    st.markdown("#### 信号收件箱（1B-0 · 只读观察）")
    st.caption(
        "真源：仓库根目录 l1_report.json。写入仅 data/virtual_portfolio/signal_inbox/。"
        "无跟单按钮。允许只读收信号 ≠ 允许自动开仓。"
    )
    rt = load_vp_runtime(root)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.write(
            f"只读收信号：**{'开' if rt.get('SIGNAL_READ_ALLOWED') else '关'}** · "
            f"信号接入/自动开仓：**关**"
        )
    with c2:
        if st.button("开启只读收信号", key="vp_sr_on"):
            set_signal_read_allowed(root, True)
            st.rerun()
    with c3:
        if st.button("关闭只读收信号", key="vp_sr_off"):
            set_signal_read_allowed(root, False)
            st.rerun()

    if st.button("摄入今日 L1 → 收件箱", key="vp_ingest_l1"):
        try:
            result = ingest_l1_to_inbox(root)
            st.info(json.dumps(result, ensure_ascii=False))
            st.rerun()
        except Exception as exc:  # noqa: BLE001 — show permission/guard errors
            st.error(str(exc))

    latest = load_inbox_latest(root)
    if latest:
        st.markdown("**最近摄入摘要**")
        st.dataframe(_df_zh(latest), hide_index=True, use_container_width=True)

    asofs = list_inbox_asofs(root)
    if asofs:
        pick = st.selectbox("按业务日查看", asofs[::-1], key="vp_inbox_asof")
        doc = load_inbox_asof(root, pick) or {}
        rows = list(doc.get("rows") or [])
        st.caption(
            f"源哈希={doc.get('source_hash') or '—'} · 行数={len(rows)} · "
            f"未映射={doc.get('n_unmapped')} · 质量警告={doc.get('n_quality_warn')}"
        )
        st.dataframe(_df_zh(rows[:200]) if rows else _df_zh({"msg": "无行"}), hide_index=True)
    else:
        st.info("收件箱为空。开启只读收信号后点击「摄入今日 L1」。")

    evs = load_inbox_events(root, limit=30)
    st.markdown("**收件箱事件尾部**")
    st.dataframe(
        _df_zh(evs) if evs else _df_zh({"msg": "暂无事件"}),
        hide_index=True,
        use_container_width=True,
    )


def render_virtual_portfolio_panel(root: Path) -> None:
    st.subheader("虚拟组合 · Phase 1A / 1B-0")
    st.caption(DISCLAIMER)

    _render_signal_inbox(root)
    st.divider()

    accounts = list_accounts(root)
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 开户")
        new_id = st.text_input("账户ID", key="vp_new_id")
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
        _df_zh(
                {
                    "ACCOUNT_MODE": acct.get("ACCOUNT_MODE"),
                    "MARGIN_STATUS": acct.get("MARGIN_STATUS") or eq.get("MARGIN_STATUS"),
                    "AUTO_OPEN_ALLOWED": acct.get("AUTO_OPEN_ALLOWED"),
                    "AUTO_CLOSE_ALLOWED": acct.get("AUTO_CLOSE_ALLOWED"),
                    "SIGNAL_INGEST_ALLOWED": acct.get("SIGNAL_INGEST_ALLOWED"),
                    "SIGNAL_READ_ALLOWED": acct.get("SIGNAL_READ_ALLOWED"),
                    "read_only_load": state.get("read_only"),
                }
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.markdown("#### 权益")
    st.dataframe(
        _df_zh(
            {
                "cash": eq.get("cash"),
                "unrealized_pnl": eq.get("unrealized_pnl"),
                "realized_pnl": eq.get("realized_pnl"),
                "equity": eq.get("equity"),
                "margin_used": eq.get("margin_used"),
                "available": eq.get("available"),
                "margin_complete": eq.get("margin_complete"),
                "flags": ",".join(eq.get("flags") or []) or "—",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("#### 持仓")
    pos = state.get("positions") or []
    st.dataframe(
        _df_zh(pos) if pos else _df_zh({"msg": "空仓"}),
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("#### 手工资金")
    c1, c2, c3 = st.columns(3)
    with c1:
        dep = st.number_input("入金金额", min_value=0.0, value=0.0, key="vp_dep")
        if st.button("入金", key="vp_dep_btn") and dep > 0:
            try:
                deposit(root, aid, dep, note="desk")
                st.rerun()
            except VpError as exc:
                st.error(str(exc))
    with c2:
        wd = st.number_input("出金金额", min_value=0.0, value=0.0, key="vp_wd")
        if st.button("出金", key="vp_wd_btn") and wd > 0:
            try:
                withdraw(root, aid, wd, note="desk")
                st.rerun()
            except VpError as exc:
                st.error(str(exc))

    st.markdown("#### 手工开平（成交规则=次日开盘，自填开盘价）")
    oc1, oc2 = st.columns(2)
    with oc1:
        sym = st.text_input("品种", value="MA", key="vp_sym")
        side_label = st.selectbox("方向", ["多", "空"], key="vp_side")
        side = "long" if side_label == "多" else "short"
        qty = st.number_input("手数", min_value=1, value=1, key="vp_qty")
        px = st.number_input("成交价", min_value=0.0, value=0.0, key="vp_px")
        asof = st.text_input("业务日（YYYY-MM-DD）", key="vp_asof")
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
        c_asof = st.text_input("平仓业务日", value=asof, key="vp_casof")
        if st.button("平仓", key="vp_close"):
            try:
                close_position(
                    root, aid, symbol=c_sym, qty=c_qty, price=c_px, asof=c_asof, note="desk"
                )
                st.rerun()
            except VpError as exc:
                st.error(str(exc))

    st.markdown("#### 账本尾部")
    evs = load_events(root, aid)
    tail = evs[-30:]
    st.dataframe(
        _df_zh(tail) if tail else pd.DataFrame({"说明": ["暂无流水"]}),
        hide_index=True,
        use_container_width=True,
    )
