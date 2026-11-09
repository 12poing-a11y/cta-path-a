# -*- coding: utf-8 -*-
"""Per-proxy simulated holdings (research only; separate from Path-A paper_book).

Reads ``final_positions`` / ``trade_log`` written by ``proxy_cta.py`` into
``external/strategies/proxy_*.json``. Soft-fails when files or fields are missing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

PROXY_IDS = ("proxy_cwft", "proxy_long_short_cwft", "proxy_frontnext_st")
DISCLAIMER = (
    "研究模拟持仓 · 非实盘 · 与 Path-A paper_book 分离。"
    "由本地代理（proxy_cta.py）在最后一根日线收盘后按同一等权多空规则推出，"
    "用于跟踪对照，不构成交易建议。"
)
_DIR_LABEL = {"long": "多", "short": "空"}


def load_proxy_positions(root: Path, proxy_ids: tuple[str, ...] = PROXY_IDS) -> list[dict[str, Any]]:
    """One record per proxy: ``{id, name, asof, positions, trade_log, status, note}``."""
    out: list[dict[str, Any]] = []
    for sid in proxy_ids:
        path = Path(root) / "external" / "strategies" / f"{sid}.json"
        rec: dict[str, Any] = {
            "id": sid, "name": sid, "asof": None, "curve_end": None,
            "positions": [], "trade_log": [], "status": "missing", "note": "",
        }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rec["note"] = f"缺少或无法解析 external/strategies/{sid}.json"
            out.append(rec)
            continue
        if not isinstance(data, dict):
            rec["note"] = "JSON 结构异常"
            out.append(rec)
            continue
        rec["name"] = str(data.get("name") or sid)
        rec["curve_end"] = data.get("end")
        positions = data.get("final_positions")
        if not isinstance(positions, list):
            rec["status"] = "no_positions"
            rec["note"] = "该代理 JSON 尚无 final_positions，请重跑 python proxy_cta.py"
            out.append(rec)
            continue
        rec["positions"] = [p for p in positions if isinstance(p, dict)]
        log = data.get("trade_log")
        rec["trade_log"] = [t for t in log if isinstance(t, dict)] if isinstance(log, list) else []
        rec["asof"] = data.get("positions_asof") or data.get("end")
        rec["status"] = "ready" if rec["positions"] else "flat"
        if not rec["positions"]:
            rec["note"] = "当前空仓（样本不足或无信号）"
        out.append(rec)
    return out


def _num(v: Any, nd: int = 2) -> Any:
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def positions_df(positions: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for p in positions:
        d = str(p.get("direction") or "")
        rows.append(
            {
                "品种": p.get("code"),
                "名称": p.get("name"),
                "方向": _DIR_LABEL.get(d, d or "—"),
                "权重%": _num(float(p.get("weight") or 0) * 100.0, 2),
                "理论手数": _num(p.get("lots_equiv"), 2),
                "名义(元)": _num(p.get("notional_yuan"), 0),
                "入场日": p.get("entry_date"),
                "入场价": p.get("entry_price"),
                "最新价": p.get("last_price"),
                "浮盈亏%": _num(p.get("unrealized_pct"), 2),
                "打分z": _num(p.get("score_z"), 2),
            }
        )
    return pd.DataFrame(rows)


def trade_log_df(log: list[dict[str, Any]], limit: int = 20) -> pd.DataFrame:
    rows = []
    for t in reversed(log[-limit:]):
        d = str(t.get("direction") or "")
        rows.append(
            {
                "日期": t.get("date"),
                "品种": t.get("code"),
                "动作": "开仓" if t.get("action") == "open" else "平仓",
                "方向": _DIR_LABEL.get(d, d or "—"),
                "价格": t.get("price"),
                "入场日": t.get("entry_date"),
                "平仓盈亏%": _num(t.get("pnl_pct"), 2),
            }
        )
    return pd.DataFrame(rows)


def render_proxy_positions(st, root: Path) -> None:
    """Streamlit expander under 概览对比."""
    with st.expander("本地代理·模拟持仓（研究模拟、非实盘）", expanded=False):
        st.caption(DISCLAIMER)
        for rec in load_proxy_positions(root):
            st.markdown(f"**{rec['name']}** (`{rec['id']}`)")
            if rec["status"] in ("missing", "no_positions"):
                st.caption(rec["note"])
                continue
            st.caption(
                f"持仓截止 {rec['asof'] or '—'}（下一交易日目标仓）· 曲线截止 {rec['curve_end'] or '—'}"
            )
            if rec["positions"]:
                st.dataframe(positions_df(rec["positions"]), width="stretch", hide_index=True)
            else:
                st.caption(rec["note"])
            if rec["trade_log"]:
                with st.expander(f"近期开平仓（{rec['id']}）", expanded=False):
                    st.dataframe(trade_log_df(rec["trade_log"]), width="stretch", hide_index=True)
