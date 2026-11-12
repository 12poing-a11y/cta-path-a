# -*- coding: utf-8 -*-
"""Synthetic protective-option opportunity table for the research desk."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

from desk.loaders import (
    format_variety_label,
    load_l1_report,
    load_strategy_payload,
    load_universe,
    option_hedge_defaults,
)
from desk.strategies.registry import REPO_ROOT, get_strategy

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from option_compare import (  # noqa: E402
    CODE_TO_SINA,
    EXCHANGE_LISTED_NO_SINA,
    compare_protective,
)
from option_hedge import option_premium, option_strike  # noqa: E402


DISCLAIMER = (
    "合成 ATR 权利金对照上市期权：优先新浪商品期权页，失败/无映射则回退天勤 TqSdk 链；"
    "都没有时对照列为空。仅研究观察，不构成交易建议。"
    "模拟持仓与决策页/Notion 同源：paper_book_latest（回退 final_positions）。"
    "纸面空仓时，日信号多/空仅作观察候选（手数按 1 估算，不代表已开仓）。"
    "棕榈油P：新浪无「棕榈油期权」页，走天勤 DCE.p2701 期权链。"
)


def _uni_name_mult(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    uni = load_universe(root) or {}
    name_by: dict[str, str] = {}
    mult_by: dict[str, Any] = {}
    for s in uni.get("symbols") or []:
        if not isinstance(s, dict):
            continue
        code = str(s.get("code") or "").upper()
        if not code:
            continue
        if s.get("name"):
            name_by[code] = str(s.get("name"))
        if s.get("mult") is not None:
            mult_by[code] = s.get("mult")
    return name_by, mult_by


def _variety_cell(root: Path, code: str, name: str = "") -> str:
    code_u = str(code or "").upper()
    return format_variety_label(code_u, str(name or "").strip(), root=root)


def paper_holdings_table(root: Path | None = None) -> pd.DataFrame:
    """Open paper lots for the 期权机会 page（品种=期号+中文名）."""
    root = root or REPO_ROOT
    try:
        from paper_book import load_paper_positions

        paper = load_paper_positions(root)
    except Exception:
        paper = {"positions": {}, "end": "", "source": "none"}
    name_by, _mult = _uni_name_mult(root)
    report = load_l1_report(root) or {}
    sig_by = {
        str(s.get("code") or "").upper(): s
        for s in (report.get("signals") or [])
        if isinstance(s, dict)
    }
    rows = []
    for code, pos in (paper.get("positions") or {}).items():
        if not isinstance(pos, dict):
            continue
        code_u = str(code or pos.get("code") or "").upper()
        direction = str(pos.get("direction") or "").strip()
        lots = int(pos.get("lots") or 0)
        if not code_u or direction not in ("多", "空") or lots <= 0:
            continue
        sig = sig_by.get(code_u) or {}
        name = str(sig.get("name") or pos.get("name") or name_by.get(code_u) or "")
        rows.append(
            {
                "品种": _variety_cell(root, code_u, name),
                "代码": code_u,
                "名称": name or code_u,
                "方向": direction,
                "手数": lots,
                "入场价": pos.get("entry"),
                "止损": pos.get("stop"),
                "止盈": pos.get("target"),
                "入场日": pos.get("entry_date"),
                "仓来源": paper.get("source") or "paper_book",
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["方向", "代码"]).reset_index(drop=True)
    df.attrs["asof"] = paper.get("end")
    df.attrs["source"] = paper.get("source")
    df.attrs["held_n"] = len(rows)
    return df


def _candidate_from_paper(root: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    """Open paper lots — same book as decision / Notion 持仓中."""
    try:
        from paper_book import load_paper_positions

        paper = load_paper_positions(root)
    except Exception:
        paper = {"positions": {}}
    positions = paper.get("positions") or {}
    if not positions:
        return []

    sig_by = {
        str(s.get("code") or "").upper(): s
        for s in (report.get("signals") or [])
        if isinstance(s, dict)
    }
    name_by, mult_by = _uni_name_mult(root)
    out: list[dict[str, Any]] = []
    for code, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        code_u = str(code or pos.get("code") or "").upper()
        direction = str(pos.get("direction") or "").strip()
        lots = int(pos.get("lots") or 0)
        if not code_u or direction not in ("多", "空") or lots <= 0:
            continue
        sig = dict(sig_by.get(code_u) or {})
        name = str(sig.get("name") or pos.get("name") or name_by.get(code_u) or code_u)
        # Prefer live bar fields from l1; fall back to position snapshot.
        row = {
            "code": code_u,
            "name": name,
            "direction": direction,
            "lots_l1": lots,
            "close": sig.get("close") if sig.get("close") is not None else pos.get("entry"),
            "atr": sig.get("atr") if sig.get("atr") is not None else pos.get("atr"),
            "mult": sig.get("mult") or pos.get("mult") or mult_by.get(code_u) or 0,
            "risk_per_lot": sig.get("risk_per_lot"),
            "selected": True,
            "_paper_source": paper.get("source"),
            "_paper_asof": paper.get("end"),
            "_candidate_kind": "paper",
        }
        # Skip unusable ATR (same guard as paper_book opens).
        atr = float(row.get("atr") or 0)
        close = float(row.get("close") or 0)
        if atr <= 0 or close <= 0:
            continue
        if atr >= close * 0.25 and sig.get("atr") is not None:
            # Bad daily ATR — keep position entry atr if saner
            pos_atr = float(pos.get("atr") or 0)
            if 0 < pos_atr < close * 0.25:
                row["atr"] = pos_atr
            else:
                continue
        out.append(row)
    return out


def _candidate_signals(report: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """L1 lots_l1>0 first; else observe fallback: direction 多/空 with ATR (lots=1)."""
    signals = [s for s in (report.get("signals") or []) if isinstance(s, dict)]
    selected = {
        str(c).upper() for c in (report.get("portfolio", {}).get("selected") or [])
    }
    name_by, mult_by = _uni_name_mult(root)
    out: list[dict[str, Any]] = []
    for s in signals:
        code = str(s.get("code") or "").upper()
        lots = int(s.get("lots_l1") or 0)
        direction = str(s.get("direction") or "")
        if lots <= 0 or direction not in ("多", "空") or not code:
            continue
        if selected and code not in selected and not s.get("selected"):
            continue
        row = dict(s)
        row["code"] = code
        row["name"] = str(s.get("name") or name_by.get(code) or code)
        row["mult"] = s.get("mult") or mult_by.get(code) or 0
        row["_candidate_kind"] = "l1_lots"
        out.append(row)
    if out:
        return out
    # Observe fallback: day signals with 多/空 (no paper lots). Synthetic 1 lot.
    for s in signals:
        code = str(s.get("code") or "").upper()
        direction = str(s.get("direction") or "")
        if direction not in ("多", "空") or not code:
            continue
        atr = float(s.get("atr") or 0)
        close = float(s.get("close") or 0)
        if atr <= 0 or close <= 0 or atr >= close * 0.25:
            continue
        row = dict(s)
        row["code"] = code
        row["name"] = str(s.get("name") or name_by.get(code) or code)
        row["lots_l1"] = 1
        row["mult"] = s.get("mult") or mult_by.get(code) or 0
        row["_candidate_kind"] = "l1_observe"
        out.append(row)
    return out


def build_opportunities(
    *,
    premium_atr_mult: float | None = None,
    strike_atr_mult: float | None = None,
    root: Path | None = None,
) -> pd.DataFrame:
    root = root or REPO_ROOT
    defaults = option_hedge_defaults(root)
    prem_m = float(premium_atr_mult if premium_atr_mult is not None else defaults["premium_atr_mult"])
    strike_m = float(strike_atr_mult if strike_atr_mult is not None else defaults["strike_atr_mult"])

    report = load_l1_report(root)
    if not report:
        return pd.DataFrame()

    uni = load_universe(root) or {}
    risk_budget = float(report.get("l1_risk_yuan") or 0)
    equity = float(report.get("equity") or report.get("equity_base") or 0)
    observe_eq = float((uni.get("observe") or {}).get("equity") or 0)

    candidates = _candidate_from_paper(root, report)
    source = "paper_book"
    if not candidates:
        candidates = _candidate_signals(report, root)
        kinds = {str(c.get("_candidate_kind") or "") for c in candidates}
        source = "l1_observe" if "l1_observe" in kinds and "l1_lots" not in kinds else "l1_lots"

    rows = []
    for s in candidates:
        direction = str(s["direction"])
        lots = int(s.get("lots_l1") or 0)
        atr = float(s.get("atr") or 0)
        mult = float(s.get("mult") or 0)
        entry = float(s.get("close") or 0)
        opt_type = "保护 Put" if direction == "多" else "保护 Call"
        strike = option_strike(direction, entry, atr, strike_m) if atr > 0 else None
        premium = option_premium(
            lots=lots, atr=atr, mult=mult, premium_atr_mult=prem_m
        )
        name_risk = float(s.get("risk_per_lot") or 0) * lots
        if name_risk <= 0 and risk_budget > 0:
            name_risk = risk_budget
        prem_risk_ratio = (premium / name_risk) if name_risk > 0 else None
        code_u = str(s.get("code") or "").upper()
        name = str(s.get("name") or code_u)
        kind = str(s.get("_candidate_kind") or source)
        # Observe fallback skips live chain fetch (too slow for full board).
        if kind == "l1_observe":
            cmp = {
                "option_symbol": None,
                "listed_strike": None,
                "listed_premium": None,
                "synth_over_listed": None,
                "note": "日信号观察·无纸面手数；权利金按1手估算；实盘链未拉。",
                "source": None,
            }
        else:
            cmp = compare_protective(
                code_u,
                direction=direction,
                strike=strike,
                lots=lots,
                mult=mult,
                synth_premium=premium,
                root=root,
            )
        note = cmp.get("note") or ""
        listed_sym = cmp.get("option_symbol")
        if not listed_sym and kind != "l1_observe":
            if cmp.get("source") == "tqsdk":
                listed_sym = ""
            elif code_u in EXCHANGE_LISTED_NO_SINA:
                listed_sym = "交易所已上市·待天勤"
                note = note or EXCHANGE_LISTED_NO_SINA[code_u]
            elif code_u not in CODE_TO_SINA:
                listed_sym = "—"
            else:
                listed_sym = ""
        rows.append(
            {
                "品种": _variety_cell(root, code_u, name),
                "代码": code_u,
                "名称": name,
                "期货方向": direction,
                "建议期权": opt_type,
                "估算行权价": round(strike, 4) if strike is not None else None,
                "估算权利金(元)": round(premium, 2),
                "实盘期权": listed_sym,
                "实盘行权价": round(cmp["listed_strike"], 4)
                if cmp.get("listed_strike") is not None
                else None,
                "实盘权利金(元)": round(cmp["listed_premium"], 2)
                if cmp.get("listed_premium") is not None
                else None,
                "合成/实盘": round(cmp["synth_over_listed"], 2)
                if cmp.get("synth_over_listed") is not None
                else None,
                "对照说明": note,
                "ATR": round(atr, 4),
                "手数": lots,
                "收盘": entry,
                "乘数": mult,
                "权利金/风险预算": round(prem_risk_ratio, 3) if prem_risk_ratio is not None else None,
                "premium_atr_mult": prem_m,
                "strike_atr_mult": strike_m,
                "仓来源": kind if kind.startswith("l1_") or kind == "paper" else source,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df.attrs["equity"] = equity
        df.attrs["observe_equity"] = observe_eq
        df.attrs["asof"] = report.get("asof")
        df.attrs["book_source"] = source
    return df


def opt_hedge_backtest_kpis(root: Path | None = None) -> dict[str, Any]:
    """KPI block when path_a_opt_hedge artifact exists."""
    root = root or REPO_ROOT
    spec = get_strategy("path_a_opt_hedge", root)
    if spec is None:
        return {}
    data = load_strategy_payload(spec, root)
    if not data or data.get("_desk_missing"):
        return {}
    keys = (
        "start",
        "end",
        "ret_pct",
        "max_dd_pct",
        "gross_ret_pct",
        "gross_max_dd_pct",
        "equity_end",
        "premium_yuan",
        "hedge_payoff_yuan",
        "hedge_net_yuan",
        "cost_yuan",
        "premium_atr_mult",
        "strike_atr_mult",
        "option_hedge",
        "_desk_source",
    )
    return {k: data[k] for k in keys if k in data and data[k] is not None}
