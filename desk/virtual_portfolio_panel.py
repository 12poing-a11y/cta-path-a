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


_INBOX_STATUS_ZH = {"OK": "成功", "DUPLICATE": "重复（同日同源，未改动）", "REJECTED": "已拒绝"}
_INBOX_REASON_ZH = {
    "MISSING_L1": "缺少 l1_report.json",
    "BAD_JSON": "JSON 无法解析",
    "NOT_OBJECT": "根节点不是对象",
    "SKIPPED": "L1 本日已跳过",
    "MISSING_ASOF": "缺少业务日",
    "SIGNALS_NOT_LIST": "signals 不是列表",
}
_INBOX_FLAG_ZH = {
    "UNMAPPED": "未映射品种",
    "QUALITY_WARN": "质量警告",
    "MISSING_CODE": "缺少代码",
}
_INBOX_EVENT_ZH = {"ingest": "摄入"}

# Inbox signal rows: display order and Chinese headers (storage keys stay English).
# ``symbol`` / ``code`` are always identical in the archive, so both fold into one 品种 column;
# ticker / source_path / source_hash / idempotency_key are audit-only and stay out of the table.
_INBOX_ROW_COLS: list[tuple[str, str]] = [
    ("_variety", "品种"),
    ("bucket", "板块"),
    ("direction_raw", "方向"),
    ("selected", "日选"),
    ("lots_l1", "L1手数"),
    ("sleeve", "子策略"),
    ("align", "对齐"),
    ("action", "动作"),
    ("close", "收盘"),
    ("atr", "ATR"),
    ("bar_date", "行情日期"),
    ("signal_asof", "业务日"),
    ("flags", "标记"),
    ("received_at", "接收时间"),
]


def _universe_names(root: Path) -> dict[str, str]:
    try:
        doc = json.loads((Path(root) / "universe.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(s.get("code") or "").upper(): str(s.get("name") or "")
        for s in (doc.get("symbols") or [])
        if isinstance(s, dict)
    }


def _inbox_variety_label(root: Path, row: dict[str, Any], names: dict[str, str]) -> str:
    """``MA2701 甲醇``: contract period + Chinese name (one column; replaces code/symbol)."""
    from desk.loaders import format_variety_label

    code = str(row.get("code") or row.get("symbol") or "").upper()
    if not code:
        return "—"
    name = str(row.get("name") or names.get(code) or "")
    return format_variety_label(code, name, root=root)


def _inbox_rows_df(root: Path, rows: list[dict[str, Any]]) -> pd.DataFrame:
    names = _universe_names(root)
    labels: dict[str, str] = {}  # one dominant-contract lookup per code
    out: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("code") or row.get("symbol") or "").upper()
        if code not in labels:
            labels[code] = _inbox_variety_label(root, row, names)
        item: dict[str, Any] = {}
        for key, zh in _INBOX_ROW_COLS:
            if key == "_variety":
                v: Any = labels[code]
            else:
                v = row.get(key)
                if key == "selected":
                    v = "是" if v else "否"
                elif key == "flags":
                    v = "、".join(_INBOX_FLAG_ZH.get(str(f), str(f)) for f in (v or [])) or "—"
                elif v is None or v == "":
                    v = "—"
            item[zh] = v
        out.append(item)
    return pd.DataFrame(out)


def _inbox_summary_df(root: Path, latest: dict[str, Any]) -> pd.DataFrame:
    """Chinese one-row summary of the latest ingest (latest.json + its by_asof doc for warn counts)."""
    asof = str(latest.get("signal_asof") or "")
    doc = load_inbox_asof(root, asof) if asof else None
    doc = doc or {}
    status = str(latest.get("status") or "")
    item: dict[str, Any] = {
        "状态": _INBOX_STATUS_ZH.get(status, status or "—"),
        "业务日": asof or "—",
        "接收时间": latest.get("received_at") or "—",
        "信号行数": latest.get("n_rows"),
        "未映射品种": latest.get("n_unmapped"),
        "质量警告行数": doc.get("n_quality_warn", "—"),
        "L1质量": ("通过" if doc.get("quality_ok") else "未通过") if "quality_ok" in doc else "—",
        "源哈希(前12位)": str(latest.get("source_hash") or "")[:12] or "—",
        "归档文件": latest.get("by_asof_rel") or "—",
    }
    return pd.DataFrame([item])


def _ingest_result_df(result: dict[str, Any]) -> pd.DataFrame:
    status = str(result.get("status") or "")
    item: dict[str, Any] = {
        "状态": _INBOX_STATUS_ZH.get(status, status or "—"),
        "业务日": result.get("signal_asof") or "—",
        "信号行数": result.get("n_rows", "—"),
        "未映射品种": result.get("n_unmapped", "—"),
        "接收时间": result.get("received_at") or "—",
    }
    if result.get("reason"):
        item["原因"] = _INBOX_REASON_ZH.get(str(result["reason"]), str(result["reason"]))
    return pd.DataFrame([item])


def _inbox_events_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for r in rows:
        status = str(r.get("status") or "")
        reason = str(r.get("reason") or "")
        out.append(
            {
                "接收时间": r.get("received_at") or "—",
                "事件": _INBOX_EVENT_ZH.get(str(r.get("event") or ""), r.get("event") or "—"),
                "状态": _INBOX_STATUS_ZH.get(status, status or "—"),
                "业务日": r.get("signal_asof") or "—",
                "信号行数": r.get("n_rows", "—"),
                "原因": _INBOX_REASON_ZH.get(reason, reason) if reason else "—",
                "备注": ("同业务日、同源哈希" if r.get("note") == "same asof+source_hash" else r.get("note")) or "—",
                "源哈希(前12位)": str(r.get("source_hash") or "")[:12] or "—",
            }
        )
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
            # Keep the result across st.rerun() so the summary is visible after ingest.
            st.session_state["vp_last_ingest"] = ingest_l1_to_inbox(root)
            st.rerun()
        except Exception as exc:  # noqa: BLE001 — show permission/guard errors
            st.error(str(exc))

    last_ingest = st.session_state.get("vp_last_ingest")
    if last_ingest:
        st.markdown("**本次摄入结果**")
        st.dataframe(_ingest_result_df(last_ingest), hide_index=True, use_container_width=True)

    latest = load_inbox_latest(root)
    if latest:
        st.markdown("**最近摄入摘要**")
        st.dataframe(_inbox_summary_df(root, latest), hide_index=True, use_container_width=True)

    asofs = list_inbox_asofs(root)
    if asofs:
        pick = st.selectbox("按业务日查看", asofs[::-1], key="vp_inbox_asof")
        doc = load_inbox_asof(root, pick) or {}
        rows = list(doc.get("rows") or [])
        st.caption(
            f"源哈希={doc.get('source_hash') or '—'} · 行数={len(rows)} · "
            f"未映射={doc.get('n_unmapped')} · 质量警告={doc.get('n_quality_warn')}"
        )
        st.dataframe(
            _inbox_rows_df(root, rows[:200]) if rows else pd.DataFrame({"说明": ["无行"]}),
            hide_index=True,
            use_container_width=True,
        )
        st.caption("品种列 = 期号 + 中文名（原代码与品种两列合并）。")
    else:
        st.info("收件箱为空。开启只读收信号后点击「摄入今日 L1」。")

    evs = load_inbox_events(root, limit=30)
    st.markdown("**收件箱事件尾部**")
    st.dataframe(
        _inbox_events_df(evs) if evs else pd.DataFrame({"说明": ["暂无事件"]}),
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
