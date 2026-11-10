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
    "Y": "豆油期权",
    "I": "铁矿石期权",
    "AL": "沪铝期权",
}

# Exchange-listed commodity options that sina optionsDP currently does not expose.
# Fall back to TqSdk option chain (e.g. DCE 棕榈油 P).
EXCHANGE_LISTED_NO_SINA: dict[str, str] = {
    "P": "棕榈油期权（大商所已上市；新浪期权页暂无链 → 回退天勤 TqSdk）",
}

# Process-local cache: underlying contract → tqsdk snapshot
_TQ_CHAIN_CACHE: dict[str, dict[str, Any]] = {}


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


def _underlying_contract(code: str, root: Path | None = None) -> str:
    """Resolve Path-A code → delivery-month contract (e.g. P → P2701)."""
    code = str(code or "").upper()
    try:
        from desk.loaders import dominant_contract_symbol

        sym = dominant_contract_symbol(root or ROOT, code)
        if sym:
            return sym
    except Exception:
        pass
    # Fallback: current observe month used by gamma wall
    return f"{code}2701"


def _tq_chain(underlying: str, *, root: Path | None = None) -> dict[str, Any]:
    key = str(underlying or "").upper()
    if key in _TQ_CHAIN_CACHE:
        return _TQ_CHAIN_CACHE[key]
    try:
        from tqsdk_client import fetch_option_chain_snapshot

        snap = fetch_option_chain_snapshot(key, root=root or ROOT, max_options=120)
    except Exception as exc:  # noqa: BLE001
        snap = {"rows": [], "notes": [f"tqsdk-import:{type(exc).__name__}:{exc}"], "source": "tqsdk"}
    if not isinstance(snap, dict):
        snap = {"rows": [], "notes": ["bad-snap"], "source": "tqsdk"}
    _TQ_CHAIN_CACHE[key] = snap
    return snap


def _pick_tq_leg(
    rows: list[dict[str, Any]],
    *,
    want_put: bool,
    strike_target: float,
) -> dict[str, Any] | None:
    side = "P" if want_put else "C"
    best = None
    best_dist = None
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("期权类型") or "").upper()[:1] != side:
            continue
        strike = _num(r.get("行权价"))
        px = _num(r.get("最新价"))
        if strike is None or px is None or px <= 0:
            continue
        dist = abs(strike - strike_target)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = {
                "strike": strike,
                "last": px,
                "symbol": str(r.get("合约代码") or r.get("tq_symbol") or ""),
                "dist": dist,
                "iv": _num(r.get("隐含波动率")),
                "oi": _num(r.get("持仓量")),
            }
    return best


def compare_protective_tqsdk(
    code: str,
    *,
    direction: str,
    strike: float | None,
    lots: int,
    mult: float,
    synth_premium: float,
    root: Path | None = None,
    contract: str | None = None,
) -> dict[str, Any]:
    """Nearest protective option from TqSdk live chain (OI + last + IV)."""
    code = str(code or "").upper()
    empty = {
        "ok": False,
        "product": EXCHANGE_LISTED_NO_SINA.get(code) or CODE_TO_SINA.get(code) or code,
        "option_symbol": "",
        "listed_strike": None,
        "listed_px": None,
        "listed_premium": None,
        "synth_over_listed": None,
        "source": "tqsdk",
        "note": "天勤期权链不可用",
    }
    if strike is None or lots <= 0 or mult <= 0:
        return empty
    und = str(contract or _underlying_contract(code, root)).upper()
    snap = _tq_chain(und, root=root)
    rows = [r for r in (snap.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        notes = "; ".join(str(n) for n in (snap.get("notes") or [])[:3])
        empty["note"] = f"天勤无期权链 {und}" + (f"（{notes}）" if notes else "")
        return empty
    want_put = direction == "多"
    leg = _pick_tq_leg(rows, want_put=want_put, strike_target=float(strike))
    if not leg:
        empty["note"] = f"天勤 {und} 链上无有效保护腿报价"
        return empty
    px = float(leg["last"])
    listed_premium = abs(lots) * px * float(mult)
    ratio = (synth_premium / listed_premium) if listed_premium > 0 else None
    side = "Put" if want_put else "Call"
    return {
        "ok": True,
        "product": f"{code}@{und}",
        "month": und,
        "option_symbol": leg.get("symbol") or "",
        "listed_strike": leg.get("strike"),
        "listed_px": px,
        "listed_premium": listed_premium,
        "synth_over_listed": ratio,
        "source": "tqsdk",
        "iv": leg.get("iv"),
        "oi": leg.get("oi"),
        "note": f"天勤期权链 {und} · 保护{side}",
    }


def compare_protective(
    code: str,
    *,
    direction: str,
    strike: float | None,
    lots: int,
    mult: float,
    synth_premium: float,
    root: Path | None = None,
    contract: str | None = None,
    prefer: str = "auto",
) -> dict[str, Any]:
    """Nearest listed protective option vs ATR synthetic premium.

    Source order (``prefer=auto``):
    1. 新浪商品期权页（有映射时）
    2. 天勤 TqSdk 期权链（新浪失败 / 无映射 / EXCHANGE_LISTED_NO_SINA）

    Returns keys used by the desk; ``ok`` is False when unavailable.
    """
    code = str(code or "").upper()
    prefer = str(prefer or "auto").lower()
    product = CODE_TO_SINA.get(code)
    empty = {
        "ok": False,
        "product": product or EXCHANGE_LISTED_NO_SINA.get(code) or "",
        "option_symbol": "",
        "listed_strike": None,
        "listed_px": None,
        "listed_premium": None,
        "synth_over_listed": None,
        "source": "",
        "note": "无对应商品期权" if not product and code not in EXCHANGE_LISTED_NO_SINA else "未取到期权链",
    }
    if strike is None or lots <= 0 or mult <= 0:
        return empty

    use_sina = prefer in ("auto", "sina") and bool(product)
    use_tq = prefer in ("auto", "tqsdk", "tq") or code in EXCHANGE_LISTED_NO_SINA

    if use_sina:
        months = list_months(product or "")
        if months:
            month = months[0]
            frame = _chain_table(product or "", month)
            want_put = direction == "多"
            leg = _pick_leg(frame, want_put=want_put, strike_target=float(strike))
            if leg:
                px = float(leg["last"])
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
                    "source": "sina",
                    "note": "新浪期权链近月 · 保护" + ("Put" if want_put else "Call"),
                }
            empty["note"] = f"{month} 新浪链无有效报价"
        else:
            empty["note"] = "新浪无近月期权合约" if product else empty["note"]

    if use_tq or prefer == "auto":
        tq = compare_protective_tqsdk(
            code,
            direction=direction,
            strike=strike,
            lots=lots,
            mult=mult,
            synth_premium=synth_premium,
            root=root,
            contract=contract,
        )
        if tq.get("ok"):
            return tq
        if not empty.get("note") or empty["note"] in ("未取到期权链", "无对应商品期权"):
            empty["note"] = tq.get("note") or empty["note"]
        elif tq.get("note"):
            empty["note"] = f"{empty['note']}；{tq.get('note')}"

    return empty
