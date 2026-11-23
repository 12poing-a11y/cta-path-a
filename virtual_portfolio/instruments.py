# -*- coding: utf-8 -*-
"""Versioned VP instrument table — never writes universe.json."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

INSTRUMENTS_REL = Path("configs") / "virtual_portfolio" / "instruments_v1.json"
MARGIN_TIERS = ("exchange", "broker", "stress")


def instruments_path(root: Path) -> Path:
    return Path(root) / INSTRUMENTS_REL


def load_instruments(root: Path) -> dict[str, Any]:
    path = instruments_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"missing VP instruments: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _asof_ok(row: dict[str, Any], asof: str | None) -> bool:
    if not asof:
        return True
    d0 = row.get("effective_from")
    d1 = row.get("effective_to")
    if d0 and asof < str(d0):
        return False
    if d1 and asof > str(d1):
        return False
    return True


def get_instrument(
    root: Path,
    instrument_id: str,
    *,
    asof: str | None = None,
) -> dict[str, Any] | None:
    cfg = load_instruments(root)
    code = str(instrument_id or "").upper()
    for row in cfg.get("rows") or []:
        if str(row.get("instrument_id") or "").upper() != code:
            continue
        if not _asof_ok(row, asof):
            continue
        return dict(row)
    return None


def margin_rate(
    row: dict[str, Any],
    *,
    side: str,
    tier: str = "broker",
) -> float | None:
    side_l = "long" if str(side).lower() in ("long", "buy", "1") else "short"
    tier = tier if tier in MARGIN_TIERS else "broker"
    key = f"margin_rate_{side_l}_{tier}"
    val = row.get(key)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def resolve_margin(
    row: dict[str, Any],
    *,
    side: str,
    preferred_tier: str = "broker",
) -> tuple[float | None, str, list[str]]:
    """Return (rate, tier_used, flags). Missing → (None, '', ['MARGIN_DATA_MISSING'])."""
    flags: list[str] = []
    order = [preferred_tier] + [t for t in MARGIN_TIERS if t != preferred_tier]
    for tier in order:
        rate = margin_rate(row, side=side, tier=tier)
        if rate is not None:
            if row.get("verified_at") is None:
                flags.append("MARGIN_UNVERIFIED")
            return rate, tier, flags
    flags.append("MARGIN_DATA_MISSING")
    return None, "", flags


def commission_meta(row: dict[str, Any], *, kind: str = "open") -> dict[str, float]:
    """Map VP commission block → fill_cost-compatible meta."""
    key = {
        "open": "commission_open",
        "close": "commission_close",
        "close_today": "commission_close_today",
    }.get(kind, "commission_open")
    block = row.get(key)
    flags: list[str] = []
    if kind == "close_today" and not block:
        block = row.get("commission_close")
        flags.append("CLOSE_TODAY_FEE_UNKNOWN")
    block = block or {}
    meta = {
        "mult": float(row.get("contract_multiplier") or 0),
        "tick": float(row.get("tick_size") or 0),
        "fee_yuan": float(block.get("fee_yuan") or 0),
        "fee_rate": float(block.get("fee_rate") or 0),
    }
    meta["_flags"] = flags  # type: ignore[assignment]
    return meta


def slippage_ticks_default(root: Path) -> float:
    cfg = load_instruments(root)
    try:
        return float(cfg.get("slippage_ticks_default") or 1.0)
    except (TypeError, ValueError):
        return 1.0


def today_iso() -> str:
    return date.today().isoformat()
