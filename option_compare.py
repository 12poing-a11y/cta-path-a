# -*- coding: utf-8 -*-
"""Compare synthetic ATR option premium to nearest sina commodity option quote.

Soft-fails when the variety has no listed option on sina, or when the chain
request errors. Desk shows empty compare columns in that case.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# Path-A codes that map to a sina commodity-option product page.
CODE_TO_SINA: dict[str, str] = {
    "M": "豆粕期权",
    "EG": "乙二醇期权",
    "EB": "苯乙烯期权",
    "TA": "PTA期权",
    "MA": "甲醇期权",
    "CF": "棉花期权",
    "SR": "白糖期权",
    "RU": "橡胶期权",
    "AG": "白银期权",
    "RB": "螺纹钢期权",
    "RM": "菜籽粕期权",
    "OI": "菜籽油期权",
    "PG": "液化石油气期权",
}


def _cache_path(name: str) -> Path:
    return ROOT / ".cache" / "akshare" / "options" / name


def _read_json(path: Path) -> Any | None:
    if not path.is_file() or path.stat().st_size < 2:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _col(frame, *needles: str) -> str | None:
    cols = [str(c) for c in getattr(frame, "columns", [])]
    for needle in needles:
        for col in cols:
            if needle in col:
                return col
    return None


def list_months(product: str) -> list[str]:
    """Futures months that currently have an option chain on sina."""
    key = re.sub(r"\W+", "_", product)
    path = _cache_path(f"months_{key}.json")
    cached = _read_json(path)
    if isinstance(cached, dict) and cached.get("months"):
        return [str(m) for m in cached["months"]]
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        frame = ak.option_commodity_contract_sina(symbol=product)
    except Exception:
        return []
    months: list[str] = []
    if frame is not None and hasattr(frame, "columns"):
        # second column is the contract month code
        col = frame.columns[1] if len(frame.columns) > 1 else frame.columns[0]
        for val in frame[col].tolist():
            text = str(val or "").strip().lower()
            if text:
                months.append(text)
    if months:
        _write_json(path, {"product": product, "months": months})
    return months


def _chain_table(product: str, month: str):
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        return ak.option_commodity_contract_table_sina(symbol=product, contract=month)
    except Exception:
        return None


def _pick_leg(frame, *, want_put: bool, strike_target: float) -> dict[str, Any] | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    strike_col = _col(frame, "行权价")
    if want_put:
        px_col = _col(frame, "看跌合约-最新价")
        id_col = _col(frame, "看跌合约-标识期权合约", "看跌合约-标识")
        if id_col is None:
            for col in frame.columns:
                sample = str(frame[col].iloc[0] if len(frame) else "")
                if re.search(r"[A-Za-z]+\d{3,4}P\d+", sample, re.I):
                    id_col = col
                    break
        # akshare layout: put last price is usually column index 12.
        if px_col is None and len(frame.columns) >= 13:
            px_col = frame.columns[12]
    else:
        px_col = _col(frame, "看涨合约-最新价")
        id_col = _col(frame, "看涨合约-标识期权合约", "看涨合约-标识")
        if id_col is None:
            for col in frame.columns:
                sample = str(frame[col].iloc[0] if len(frame) else "")
                if re.search(r"[A-Za-z]+\d{3,4}C\d+", sample, re.I):
                    id_col = col
                    break
        if px_col is None and len(frame.columns) >= 3:
            px_col = frame.columns[2]
    if strike_col is None or px_col is None:
        return None
    best = None
    best_dist = None
    for _, row in frame.iterrows():
        strike = _num(row.get(strike_col))
        px = _num(row.get(px_col))
        if strike is None or px is None or px <= 0:
            continue
        dist = abs(strike - strike_target)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            opt_id = str(row.get(id_col) or "") if id_col else ""
            best = {
                "strike": strike,
                "last": px,
                "symbol": opt_id,
                "dist": dist,
            }
    return best


def hist_last_close(option_symbol: str) -> float | None:
    if not option_symbol:
        return None
    path = _cache_path(f"hist_{option_symbol}.json")
    cached = _read_json(path)
    if isinstance(cached, dict) and _num(cached.get("close")) is not None:
        return float(cached["close"])
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        frame = ak.option_commodity_hist_sina(symbol=option_symbol)
    except Exception:
        return None
    if frame is None or getattr(frame, "empty", True):
        return None
    close_col = "close" if "close" in frame.columns else frame.columns[-2]
    last = _num(frame.iloc[-1].get(close_col))
    if last is None:
        return None
    _write_json(path, {"symbol": option_symbol, "close": last})
    return float(last)


def compare_protective(
    code: str,
    *,
    direction: str,
    strike: float | None,
    lots: int,
    mult: float,
    synth_premium: float,
) -> dict[str, Any]:
    """Nearest listed protective option vs ATR synthetic premium.

    Returns keys used by the desk; ``ok`` is False when unavailable.
    """
    code = str(code or "").upper()
    product = CODE_TO_SINA.get(code)
    empty = {
        "ok": False,
        "product": product or "",
        "option_symbol": "",
        "listed_strike": None,
        "listed_px": None,
        "listed_premium": None,
        "synth_over_listed": None,
        "note": "无对应商品期权" if not product else "未取到期权链",
    }
    if not product or strike is None or lots <= 0 or mult <= 0:
        return empty
    months = list_months(product)
    if not months:
        empty["note"] = "无近月期权合约"
        return empty
    month = months[0]
    frame = _chain_table(product, month)
    want_put = direction == "多"
    leg = _pick_leg(frame, want_put=want_put, strike_target=float(strike))
    if not leg:
        empty["note"] = f"{month} 链上无有效报价"
        return empty
    px = float(leg["last"])
    # Prefer daily hist close when the chain quote looks like a stub.
    hist_px = hist_last_close(str(leg.get("symbol") or ""))
    if hist_px is not None and hist_px > 0:
        px = hist_px
    listed_premium = abs(lots) * px * float(mult)
    ratio = (synth_premium / listed_premium) if listed_premium > 0 else None
    return {
        "ok": True,
        "product": product,
        "month": month,
        "option_symbol": leg.get("symbol") or "",
        "listed_strike": leg.get("strike"),
        "listed_px": px,
        "listed_premium": listed_premium,
        "synth_over_listed": ratio,
        "note": "新浪期权链近月 · 保护" + ("Put" if want_put else "Call"),
    }
