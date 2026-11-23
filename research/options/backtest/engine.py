# -*- coding: utf-8 -*-
"""Credit-vertical research backtest over chain snapshots.

No Path-A formal writes. Entry uses only same-day snapshot fields (no lookahead).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from research.options.chain_store import load_chain_series
from research.options.backtest.metrics import summarize_trades
from research.options.specs import credit_vertical_margin_cny
from research.options.strategies.credit_vertical import (
    expiry_pnl_points,
    mtm_close_debit,
    select_credit_vertical,
)

ExitMode = Literal["next_snap", "expiry"]
OUT_REL = Path("data") / "options" / "backtests"
LATEST_NAME = "credit_vertical_latest.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def backtest_dir(root: Path) -> Path:
    d = Path(root) / OUT_REL
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_credit_vertical_bt(
    root: Path,
    *,
    codes: list[str] | None = None,
    kind: str = "put_credit",
    width_points: float = 200.0,
    slip_ticks: float = 2.0,
    exit_mode: ExitMode = "next_snap",
    max_margin_cny: float | None = None,
    stop_loss_mult: float | None = 2.0,
    prefer_bid_ask: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    """Run research BT. Skips REJECT quality days. Caps status at WARN without bid/ask."""
    codes = [c.upper() for c in (codes or ["CF", "SR", "MA"])]
    trades: list[dict[str, Any]] = []
    for code in codes:
        series = load_chain_series(root, code)
        if len(series) < 2 and exit_mode == "next_snap":
            trades.append(
                {
                    "status": "skipped",
                    "code": code,
                    "reason": "need_ge_2_snapshots",
                }
            )
            continue
        for i, snap in enumerate(series):
            qstat = (snap.get("quality") or {}).get("status")
            if qstat == "REJECT":
                trades.append(
                    {
                        "status": "skipped",
                        "code": code,
                        "asof": snap.get("asof"),
                        "reason": "quality_reject",
                        "quality": snap.get("quality"),
                    }
                )
                continue
            # No lookahead: entry decision uses snap[i] only
            sel = select_credit_vertical(
                snap,
                kind=kind,  # type: ignore[arg-type]
                width_points=width_points,
                slip_ticks=slip_ticks,
                prefer_bid_ask=prefer_bid_ask,
            )
            if sel is None:
                trades.append(
                    {
                        "status": "skipped",
                        "code": code,
                        "asof": snap.get("asof"),
                        "reason": "no_legs_or_credit",
                    }
                )
                continue
            margin = credit_vertical_margin_cny(
                width_points=float(sel["width_points"]),
                credit_points=float(sel["credit_points"]),
                multiplier=float(sel["multiplier"]),
            )
            if max_margin_cny is not None and margin > float(max_margin_cny):
                trades.append(
                    {
                        "status": "skipped",
                        "code": code,
                        "asof": snap.get("asof"),
                        "reason": "margin_cap",
                        "margin_est_cny": margin,
                    }
                )
                continue

            trade: dict[str, Any] = {
                **sel,
                "status": "open",
                "entry_asof": sel.get("asof"),
                "margin_est_cny": margin,
                "strategy_state": "WARN" if sel.get("pricing_mode") == "settle_discount" else "RESEARCH",
            }

            exit_asof = None
            pnl_points = None
            exit_debit = None
            exit_reason = None

            if exit_mode == "next_snap":
                if i + 1 >= len(series):
                    trade["status"] = "skipped"
                    trade["reason"] = "no_next_snap"
                    trades.append(trade)
                    continue
                nxt = series[i + 1]
                # Guard: exit snap date must be strictly after entry
                if str(nxt.get("asof") or "") <= str(snap.get("asof") or ""):
                    trade["status"] = "skipped"
                    trade["reason"] = "exit_not_after_entry"
                    trades.append(trade)
                    continue
                debit = mtm_close_debit(nxt, sel)
                if debit is None:
                    trade["status"] = "skipped"
                    trade["reason"] = "exit_legs_missing"
                    trades.append(trade)
                    continue
                exit_debit = debit
                pnl_points = float(sel["credit_points"]) - float(debit)
                exit_asof = nxt.get("asof")
                exit_reason = "next_snap"
                if stop_loss_mult is not None and debit >= float(stop_loss_mult) * float(sel["credit_points"]):
                    exit_reason = "stop_loss_mtm"
            else:
                # Expiry: need underlying settle on a terminal snap or same snap if expiry==asof (rare)
                term = series[-1]
                F = term.get("underlying_settle")
                if F is None:
                    trade["status"] = "skipped"
                    trade["reason"] = "expiry_F_missing"
                    trades.append(trade)
                    continue
                if str(term.get("asof") or "") < str(snap.get("asof") or ""):
                    trade["status"] = "skipped"
                    trade["reason"] = "expiry_before_entry"
                    trades.append(trade)
                    continue
                # Only one trade per code in expiry mode from each entry day would explode;
                # still allow but mark exit as terminal snap proxy for expiry.
                pnl_points = expiry_pnl_points(
                    kind=kind,  # type: ignore[arg-type]
                    short_strike=float(sel["short"]["strike"]),
                    long_strike=float(sel["long"]["strike"]),
                    credit_points=float(sel["credit_points"]),
                    futures_settle=float(F),
                )
                exit_asof = term.get("asof")
                exit_reason = "expiry_proxy_last_snap"
                exit_debit = float(sel["credit_points"]) - float(pnl_points)

            max_adverse = max(0.0, -float(pnl_points))
            trade.update(
                {
                    "status": "closed",
                    "exit_asof": exit_asof,
                    "exit_debit_points": exit_debit,
                    "exit_reason": exit_reason,
                    "pnl_points": pnl_points,
                    "pnl_cny": float(pnl_points) * float(sel["multiplier"]),
                    "max_adverse_points": max_adverse,
                }
            )
            trades.append(trade)

    # Avoid double-counting: in next_snap mode each day opens; that's intentional research density.
    # In expiry mode same — research only.
    metrics = summarize_trades(trades)
    closed = [t for t in trades if t.get("status") == "closed"]
    has_ba = any(t.get("pricing_mode") == "bid_ask" for t in closed)
    if not closed:
        strategy_state = "RESEARCH"
    elif not has_ba:
        strategy_state = "WARN"  # settle_discount only — no Bid/Ask promotion
    else:
        strategy_state = "RESEARCH"

    out = {
        "schema": "cta-options-credit-bt-v1",
        "built_at": _iso_now(),
        "params": {
            "codes": codes,
            "kind": kind,
            "width_points": width_points,
            "slip_ticks": slip_ticks,
            "exit_mode": exit_mode,
            "max_margin_cny": max_margin_cny,
            "stop_loss_mult": stop_loss_mult,
            "prefer_bid_ask": prefer_bid_ask,
        },
        "strategy_state": strategy_state,
        "metrics": metrics,
        "trades": trades,
        "disclaimer": (
            "Research only; settle_discount without Bid/Ask caps at WARN; "
            "does not write paper_book or formal historical_backtest."
        ),
    }
    if write:
        path = backtest_dir(root) / LATEST_NAME
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        out["path"] = str(path)
    return out


def load_latest_bt(root: Path) -> dict[str, Any] | None:
    path = backtest_dir(root) / LATEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
