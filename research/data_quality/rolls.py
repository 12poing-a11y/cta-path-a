# -*- coding: utf-8 -*-
"""Roll helpers (R6a/b, reworked in R6b-fix).

A roll is identified **only** from the actual main-contract map
(``research.data_quality.main_map``): ``main_map[d] != main_map[d-1]`` with both
non-None.  The calendar stamp ``bar["contract"]`` and same-day open interest /
overnight-gap heuristics are NOT used (the former changes monthly for
12-month products while Sina's main does not move; the latter needs d's close).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from research.data_quality.main_map import contract_bars_by_date

ROOT = Path(__file__).resolve().parents[2]


def is_roll_day(prev_main: str | None, cur_main: str | None) -> bool:
    """True when the actual main contract changed between d-1 and d (both known)."""
    if not prev_main or not cur_main:
        return False
    return str(prev_main).upper() != str(cur_main).upper()


def _ohlc_from_snap(snap_bar: dict, contract: str) -> dict | None:
    if (
        snap_bar.get("contract_high") is None
        or snap_bar.get("contract_low") is None
        or snap_bar.get("contract_close") is None
    ):
        return None
    if contract and str(snap_bar.get("contract") or "").upper() not in ("", contract):
        return None
    try:
        close = float(snap_bar["contract_close"])
        return {
            "open": float(
                snap_bar["contract_open"] if snap_bar.get("contract_open") is not None else close
            ),
            "high": float(snap_bar["contract_high"]),
            "low": float(snap_bar["contract_low"]),
            "close": close,
            "date": str(snap_bar.get("date") or "")[:10],
            "source": "snap_contract",
        }
    except (TypeError, ValueError):
        return None


def load_contract_bar(
    contract: str,
    day: str,
    *,
    root: Path | None = None,
    snap_bar: dict | None = None,
) -> dict | None:
    """Exact-contract OHLC for ``day``: snapshot ``contract_*`` first, then the contract store
    behind ``root`` (a root path = local cache, or a ``ContractStore``)."""
    day = str(day or "")[:10]
    contract = str(contract or "").upper()
    if snap_bar is not None:
        got = _ohlc_from_snap(snap_bar, contract)
        if got is not None:
            got["date"] = day
            return got
    if not contract or len(day) != 10:
        return None
    b = contract_bars_by_date(contract, root or ROOT).get(day)
    if not b:
        return None
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


def last_contract_bar(
    contract: str,
    *,
    on_or_before: str,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Last known daily bar (with ``date``) of ``contract`` on or before ``on_or_before``."""
    contract = str(contract or "").upper()
    day = str(on_or_before or "")[:10]
    if not contract or len(day) != 10:
        return None
    by = contract_bars_by_date(contract, root or ROOT)
    best = None
    for d in sorted(by):
        if d <= day:
            best = d
        else:
            break
    if best is None:
        return None
    try:
        return {"date": best, "close": float(by[best]["close"])}
    except (KeyError, TypeError, ValueError):
        return None


def last_contract_close(
    contract: str,
    *,
    on_or_before: str,
    root: Path | None = None,
) -> float | None:
    """Last known close of ``contract`` on or before ``on_or_before``."""
    b = last_contract_bar(contract, on_or_before=on_or_before, root=root)
    return None if b is None else float(b["close"])
