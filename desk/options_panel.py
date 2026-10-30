# -*- coding: utf-8 -*-
"""Synthetic protective-option opportunity table for the research desk."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

from desk.loaders import load_l1_report, load_strategy_payload, load_universe, option_hedge_defaults
from desk.strategies.registry import REPO_ROOT, get_strategy

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from option_compare import CODE_TO_SINA, compare_protective  # noqa: E402
from option_hedge import option_premium, option_strike  # noqa: E402


DISCLAIMER = (
    "合成 ATR 权利金对照新浪商品期权近月链（有上市品种才比）；"
    "无链或拉失败时对照列为空。仅研究观察，不构成交易建议。"
    "候选仓与决策页/Notion 同源：paper_book_latest（回退 final_positions）。"
)


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
    uni = load_universe(root) or {}
    mult_by = {
        str(s.get("code") or "").upper(): s.get("mult")
        for s in (uni.get("symbols") or [])
        if isinstance(s, dict)
    }
    out: list[dict[str, Any]] = []
    for code, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        direction = str(pos.get("direction") or "").strip()
        lots = int(pos.get("lots") or 0)
        if direction not in ("多", "空") or lots <= 0:
            continue
        sig = dict(sig_by.get(code) or {})
        # Prefer live bar fields from l1; fall back to position snapshot.
        row = {
            "code": code,
            "name": sig.get("name") or code,
            "direction": direction,
            "lots_l1": lots,
            "close": sig.get("close") if sig.get("close") is not None else pos.get("entry"),
            "atr": sig.get("atr") if sig.get("atr") is not None else pos.get("atr"),
            "mult": sig.get("mult") or pos.get("mult") or mult_by.get(code) or 0,
            "risk_per_lot": sig.get("risk_per_lot"),
            "selected": True,
            "_paper_source": paper.get("source"),
            "_paper_asof": paper.get("end"),
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


def _candidate_signals(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Legacy fallback: l1 lots_l1>0 (usually empty after caps)."""
    signals = report.get("signals") or []
    selected = set(report.get("portfolio", {}).get("selected") or [])
    out: list[dict[str, Any]] = []
    for s in signals:
        code = s.get("code")
        lots = int(s.get("lots_l1") or 0)
        direction = str(s.get("direction") or "")
        if lots <= 0 or direction not in ("多", "空"):
            continue
        if selected and code not in selected:
            if not s.get("selected"):
                continue
        out.append(s)
    if out:
        return out
    for s in signals:
        lots = int(s.get("lots_l1") or 0)
        direction = str(s.get("direction") or "")
        if lots > 0 and direction in ("多", "空"):
            out.append(s)
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
        candidates = _candidate_signals(report)
        source = "l1_lots"

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
        cmp = compare_protective(
            str(s.get("code") or ""),
            direction=direction,
            strike=strike,
            lots=lots,
            mult=mult,
            synth_premium=premium,
        )
        rows.append(
            {
                "品种": s.get("code"),
                "名称": s.get("name"),
                "期货方向": direction,
                "建议期权": opt_type,
                "估算行权价": round(strike, 4) if strike is not None else None,
                "估算权利金(元)": round(premium, 2),
                "实盘期权": cmp.get("option_symbol")
                or ("—" if str(s.get("code") or "").upper() not in CODE_TO_SINA else ""),
                "实盘行权价": round(cmp["listed_strike"], 4)
                if cmp.get("listed_strike") is not None
                else None,
                "实盘权利金(元)": round(cmp["listed_premium"], 2)
                if cmp.get("listed_premium") is not None
                else None,
                "合成/实盘": round(cmp["synth_over_listed"], 2)
                if cmp.get("synth_over_listed") is not None
                else None,
                "对照说明": cmp.get("note") or "",
                "ATR": round(atr, 4),
                "手数": lots,
                "收盘": entry,
                "乘数": mult,
                "权利金/风险预算": round(prem_risk_ratio, 3) if prem_risk_ratio is not None else None,
                "premium_atr_mult": prem_m,
                "strike_atr_mult": strike_m,
                "仓来源": source,
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
