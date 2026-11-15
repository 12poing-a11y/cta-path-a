# -*- coding: utf-8 -*-
"""Readonly desk panel for listed-option credit research KPIs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from research.options.backtest.engine import load_latest_bt
from research.options.chain_store import list_snapshot_dates
from research.options.paper.ledger import load_ledger
from research.options.risk_report import build_risk_report
from research.options.upgrade_gate import assess_upgrade_readiness


DISCLAIMER = (
    "上市期权信用价差研究台：与合成 ATR 保护期权分离；"
    "无 Bid/Ask 时定价为 settle_discount，策略状态最高 WARN；"
    "不写入 Path-A paper_book / 正式回测。"
)


def snapshot_coverage(root: Path) -> pd.DataFrame:
    rows = []
    for code in ("CF", "SR", "MA"):
        dates = list_snapshot_dates(root, code)
        rows.append({"品种": code, "快照日数": len(dates), "最近": dates[-1] if dates else "—"})
    return pd.DataFrame(rows)


def bt_kpi_table(root: Path) -> tuple[dict[str, Any] | None, pd.DataFrame]:
    bt = load_latest_bt(root)
    if not bt:
        return None, pd.DataFrame()
    m = bt.get("metrics") or {}
    meta = {
        "strategy_state": bt.get("strategy_state"),
        "kind": (bt.get("params") or {}).get("kind"),
        "exit_mode": (bt.get("params") or {}).get("exit_mode"),
        "pricing_note": "settle_discount unless bid/ask present",
    }
    closed = [t for t in (bt.get("trades") or []) if t.get("status") == "closed"]
    df = pd.DataFrame(
        [
            {
                "品种": t.get("code"),
                "入场": t.get("entry_asof") or t.get("asof"),
                "出场": t.get("exit_asof"),
                "类型": t.get("kind"),
                "信用点": t.get("credit_points"),
                "PnL点": t.get("pnl_points"),
                "PnL元": t.get("pnl_cny"),
                "定价": t.get("pricing_mode"),
                "退出": t.get("exit_reason"),
            }
            for t in closed[:50]
        ]
    )
    meta["metrics"] = m
    return meta, df


def render_options_research_panel(st: Any, root: Path) -> None:
    st.subheader("上市期权 · 信用价差研究")
    st.caption(DISCLAIMER)
    try:
        gate = assess_upgrade_readiness(root)
        if gate.get("ready"):
            st.success(gate.get("reminder"))
        else:
            st.info(gate.get("reminder"))
    except Exception as exc:
        st.caption(f"升级闸门暂不可用: {exc}")
    cov = snapshot_coverage(root)
    st.markdown("**链快照覆盖**")
    st.dataframe(cov, hide_index=True, width="stretch")

    meta, df = bt_kpi_table(root)
    if meta is None:
        st.info("尚无信用价差研究回测产物。运行 `python scripts/run_options_credit_bt.py`。")
        return
    m = meta.get("metrics") or {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("状态", meta.get("strategy_state") or "—")
    c2.metric("成交笔数", m.get("n_closed"))
    c3.metric("胜率", m.get("win_rate"))
    c4.metric("均PnL(元)", m.get("avg_pnl_cny"))
    c5.metric("跳过", m.get("n_skipped"))
    st.caption(
        f"kind={meta.get('kind')} exit={meta.get('exit_mode')} · {meta.get('pricing_note')}"
    )
    if not df.empty:
        st.dataframe(df, hide_index=True, width="stretch")

    try:
        risk = build_risk_report(root, write=False)
        st.markdown("**风险摘要（研究）**")
        st.json(
            {
                "quality_reject_skips": risk.get("quality_reject_skips"),
                "ledger_n": risk.get("ledger_n"),
                "by_code": risk.get("by_code"),
            }
        )
    except Exception as exc:
        st.warning(f"风险摘要不可用: {exc}")

    ledger = load_ledger(root)
    st.caption(f"研究纸面台账行数: {len(ledger)}（data/options/paper_trades/）")
