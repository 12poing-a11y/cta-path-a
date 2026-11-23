# -*- coding: utf-8 -*-
"""Roll-day detection and exact-contract bar lookup (R6a/b).

Uses only information available on the daily bar being processed (contract
stamp is calendar ex-ante; OI/gap compare d vs d−1 on the same hist — no T+1).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# OI jump threshold below the original 40% so MA (+18%) / EG (+33%) rolls are caught;
# pair with overnight gap so quiet OI drifts do not fire.
OI_JUMP = 0.15
GAP_MIN = 0.005
# No gap-alone rule: a large overnight gap without OI/contract change is a real
# market gap, not a roll. Synthetic/no-OI series must not false-trigger R6b.


def overnight_gap(prev: dict, cur: dict) -> float | None:
    try:
        c0 = float(prev["close"])
        o1 = float(cur["open"] if cur.get("open") is not None else cur["close"])
        if c0 == 0:
            return None
        return o1 / c0 - 1.0
    except (KeyError, TypeError, ValueError):
        return None


def oi_change(prev: dict, cur: dict) -> float | None:
    try:
        o0 = float(prev.get("open_interest") or 0)
        o1 = float(cur.get("open_interest") or 0)
        if o0 <= 0:
            return None
        return o1 / o0 - 1.0
    except (TypeError, ValueError):
        return None


def is_roll_day(prev: dict | None, cur: dict | None) -> bool:
    """True when d looks like a sina/main roll vs d−1."""
    if not prev or not cur:
        return False
    c0 = str(prev.get("contract") or "").upper()
    c1 = str(cur.get("contract") or "").upper()
    if c0 and c1 and c0 != c1:
        return True
    gap = overnight_gap(prev, cur)
    oi = oi_change(prev, cur)
    if gap is None or oi is None:
        return False
    if abs(gap) >= GAP_MIN and abs(oi) >= OI_JUMP:
        return True
    return False


def load_contract_bar(
    contract: str,
    day: str,
    *,
    root: Path | None = None,
    snap_bar: dict | None = None,
) -> dict | None:
    """Exact-contract OHLC for ``day``: prefer snap contract_* then .cache/contracts."""
    day = str(day or "")[:10]
    contract = str(contract or "").upper()
    if snap_bar is not None:
        if (
            snap_bar.get("contract_high") is not None
            and snap_bar.get("contract_low") is not None
            and snap_bar.get("contract_close") is not None
            and (
                not contract
                or str(snap_bar.get("contract") or "").upper() in ("", contract)
            )
        ):
            try:
                close = float(snap_bar["contract_close"])
                return {
                    "open": float(
                        snap_bar["contract_open"]
                        if snap_bar.get("contract_open") is not None
                        else close
                    ),
                    "high": float(snap_bar["contract_high"]),
                    "low": float(snap_bar["contract_low"]),
                    "close": close,
                    "date": day,
                    "source": "snap_contract",
                }
            except (TypeError, ValueError):
                pass
    if not contract or len(day) != 10:
        return None
    root = Path(root or ROOT)
    try:
        from research.execution.contract_pack import load_exact_contract_daily
    except Exception:  # noqa: BLE001
        return None
    rows = load_exact_contract_daily(contract, root=root)
    for b in rows:
        if str(b.get("date") or "")[:10] != day:
            continue
        try:
            close = float(b["close"])
            return {
                "open": float(b["open"] if b.get("open") is not None else close),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": close,
                "date": day,
                "source": "cache_contract",
            }
        except (KeyError, TypeError, ValueError):
            return None
    return None


def last_contract_close(
    contract: str,
    *,
    on_or_before: str,
    root: Path | None = None,
) -> float | None:
    """Last known close of ``contract`` on or before ``on_or_before``."""
    contract = str(contract or "").upper()
    day = str(on_or_before or "")[:10]
    if not contract or len(day) != 10:
        return None
    root = Path(root or ROOT)
    try:
        from research.execution.contract_pack import load_exact_contract_daily
    except Exception:  # noqa: BLE001
        return None
    rows = load_exact_contract_daily(contract, root=root)
    last = None
    for b in rows:
        d = str(b.get("date") or "")[:10]
        if d <= day:
            try:
                last = float(b["close"])
            except (TypeError, ValueError):
                continue
    return last


def roll_shift_from_contracts(
    old_contract: str,
    new_contract: str,
    prev_day: str,
    *,
    root: Path | None = None,
) -> float | None:
    """(new_close − old_close) on prev_day for stop/target translation."""
    old_b = load_contract_bar(old_contract, prev_day, root=root)
    new_b = load_contract_bar(new_contract, prev_day, root=root)
    if not old_b or not new_b:
        return None
    return float(new_b["close"]) - float(old_b["close"])
