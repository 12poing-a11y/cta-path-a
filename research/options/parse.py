# -*- coding: utf-8 -*-
"""Normalize CZCE / Tq option day rows into research chain legs."""
from __future__ import annotations

import math
import re
from typing import Any

from gamma_wall import _contract_side, _num, czce_option_month


def product_from_contract(contract: str) -> tuple[str, str]:
    """CF2701 → (CF, 2701)."""
    m = re.fullmatch(r"([A-Za-z]+)(\d{4})", str(contract).strip())
    if not m:
        raise ValueError("期货合约须为品种+四位年月，例如 CF2701")
    return m.group(1).upper(), m.group(2)


def _side_from_row(row: dict[str, Any]) -> str | None:
    raw = str(row.get("期权类型") or row.get("option_class") or "").strip().upper()
    if raw.startswith("C"):
        return "C"
    if raw.startswith("P"):
        return "P"
    return None


def normalize_leg(row: dict[str, Any], product_month: str) -> dict[str, Any] | None:
    """Map one CZCE/Tq day-table row → research leg dict, or None if unparsable."""
    code = str(row.get("合约代码") or row.get("合约") or "").strip()
    parsed = _contract_side(code, product_month) if code else None
    if not parsed:
        # Tq / alternate: side + strike columns
        side = _side_from_row(row)
        strike = _num(row.get("行权价"))
        if side is None or strike is None:
            return None
        # Normalize symbol for research fingerprinting
        code = code or f"{product_month}{side}{int(strike) if float(strike).is_integer() else strike}"
    else:
        side, strike = parsed

    settle = _num(row.get("今结算"))
    if settle is None:
        settle = _num(row.get("结算价"))
    close = _num(row.get("今收盘"))
    if close is None:
        close = _num(row.get("收盘价"))
    if close is None:
        close = _num(row.get("最新价"))
    if settle is None:
        settle = close  # live Tq: last as settle proxy

    oi = _num(row.get("持仓量"))
    if oi is None:
        oi = _num(row.get("空盘量"))
    volume = _num(row.get("成交量(手)"))
    if volume is None:
        volume = _num(row.get("成交量"))
    iv = _num(row.get("隐含波动率"))
    if iv is not None and iv > 3:
        iv = iv / 100.0
    delta = _num(row.get("DELTA"))
    if delta is None:
        delta = _num(row.get("Delta"))

    bid = _num(row.get("买价"))
    if bid is None:
        bid = _num(row.get("bid"))
    if bid is None:
        bid = _num(row.get("bid_price1"))
    if bid is None:
        bid = _num(row.get("bid_price"))
    ask = _num(row.get("卖价"))
    if ask is None:
        ask = _num(row.get("ask"))
    if ask is None:
        ask = _num(row.get("ask_price1"))
    if ask is None:
        ask = _num(row.get("ask_price"))

    return {
        "symbol": str(code).upper().replace("-", "").replace(" ", ""),
        "side": side,
        "strike": float(strike),
        "settle": float(settle) if settle is not None and math.isfinite(settle) else None,
        "close": float(close) if close is not None and math.isfinite(close) else None,
        "bid": float(bid) if bid is not None and math.isfinite(bid) and bid > 0 else None,
        "ask": float(ask) if ask is not None and math.isfinite(ask) and ask > 0 else None,
        "oi": float(oi) if oi is not None and math.isfinite(oi) else None,
        "volume": float(volume) if volume is not None and math.isfinite(volume) else None,
        "exchange_iv": float(iv) if iv is not None and math.isfinite(iv) else None,
        "delta": float(delta) if delta is not None and math.isfinite(delta) else None,
    }


def legs_from_czce_rows(
    option_rows: list[dict[str, Any]],
    *,
    futures_contract: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Return (option_month, legs) for the futures delivery month series."""
    product, yymm = product_from_contract(futures_contract)
    month = czce_option_month(f"{product}{yymm}")
    legs: list[dict[str, Any]] = []
    for row in option_rows:
        if not isinstance(row, dict):
            continue
        leg = normalize_leg(row, month)
        if leg is not None:
            legs.append(leg)
    legs.sort(key=lambda x: (x["side"], x["strike"]))
    return month, legs
