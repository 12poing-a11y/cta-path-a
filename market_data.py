# -*- coding: utf-8 -*-
"""Futures daily bars: Sina and Tencent first, iFinD only fills gaps."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
_MEM: dict[str, list] = {}
_FREE: dict[str, tuple] = {}

SINA_DAILY_URL = (
    "https://stock2.finance.sina.com.cn/futures/api/json.php/"
    "InnerFuturesNewService.getDailyKLine"
)
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn",
}
TENCENT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://gu.qq.com/",
}


def sina_symbol(code: str) -> str:
    """Main continuous contract on Sina, e.g. MA -> MA0, M -> M0."""
    return f"{str(code or '').upper()}0"


def tencent_symbol(code: str) -> str:
    """Tencent futures-style symbol. Public kline currently rejects these."""
    return f"nf_{sina_symbol(code)}"


def _iso_date(value) -> str:
    s = str(value or "").strip().replace("/", "-")
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return s[:10]


def _f(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bar(d: str, open_, high, low, close, volume=None, oi=None, settle=None) -> dict | None:
    d = _iso_date(d)
    if not d or close is None or close <= 0:
        return None
    if high is None:
        high = close
    if low is None:
        low = close
    if open_ is None:
        open_ = close
    if high < low:
        high, low = low, high
    # Same guard as the iFinD parser: a bar wider than 5x is not a daily range.
    if low <= 0 or high / low > 5:
        return None
    return {
        "date": d,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_interest": oi,
        "settle": settle,
    }


def fetch_sina_symbol(symbol: str, timeout: float = 20) -> list[dict]:
    """Sina daily bars for a continuous or delivery-month symbol.

    IndexService.getInnerFuturesDailyKLine stops in 2024-07. NewService
    returns date/ohlc/volume/open interest/settlement through the current day.
    Same-day responses are cached so a filter comparison does not refetch.
    """
    symbol = str(symbol or "").upper()
    if not symbol:
        return []
    if symbol in _MEM:
        return _MEM[symbol]
    cache = ROOT / ".cache" / "sina" / date.today().isoformat() / f"{symbol}.json"
    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                _MEM[symbol] = cached
                return cached
        except Exception:
            pass
    resp = requests.get(
        SINA_DAILY_URL,
        params={"symbol": symbol},
        headers=HTTP_HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        _MEM[symbol] = []
        return []
    out = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        bar = _bar(
            str(row.get("d") or ""),
            _f(row.get("o")),
            _f(row.get("h")),
            _f(row.get("l")),
            _f(row.get("c")),
            _f(row.get("v")),
            _f(row.get("p")),
            _f(row.get("s")),
        )
        if bar:
            out.append(bar)
    out.sort(key=lambda b: b["date"])
    _MEM[symbol] = out
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out


def fetch_sina_daily(code: str, timeout: float = 20) -> list[dict]:
    """Main-continuous daily bars, symbol `{CODE}0`."""
    return fetch_sina_symbol(sina_symbol(code), timeout=timeout)


def fetch_tencent_daily(code: str, timeout: float = 8) -> list[dict]:
    """Tencent daily kline. Commodity symbols currently return param error.

    Row order on the stock endpoint is date, open, close, high, low, volume.
    The same order is used if a futures symbol ever starts returning bars.
    """
    sym = tencent_symbol(code)
    resp = requests.get(
        TENCENT_KLINE_URL,
        params={"param": f"{sym},day,,,800,"},
        headers=TENCENT_HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    node = data.get(sym) or data.get(sym.lower()) or data.get(sym.upper())
    if not isinstance(node, dict):
        return []
    rows = node.get("day") or node.get("qfqday") or []
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        # date, open, close, high, low, volume
        bar = _bar(
            str(row[0]),
            _f(row[1]),
            _f(row[3]),
            _f(row[4]),
            _f(row[2]),
            _f(row[5]) if len(row) > 5 else None,
        )
        if bar:
            out.append(bar)
    out.sort(key=lambda b: b["date"])
    return out


def merge_bars(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """Primary overwrites secondary on the same date. Secondary fills holes."""
    by: dict[str, dict] = {}
    for src in (secondary, primary):
        for bar in src:
            d = bar.get("date")
            if not d:
                continue
            row = by.setdefault(d, {"date": d})
            for key, value in bar.items():
                if key == "date" or value is None:
                    continue
                row[key] = value
    return [by[k] for k in sorted(by)]


def series_sufficient(bars: list[dict], min_bars: int, max_stale_days: int = 12) -> bool:
    if len(bars) < min_bars:
        return False
    last = bars[-1]
    if not last.get("close") or not last.get("high") or not last.get("low"):
        return False
    try:
        last_d = date.fromisoformat(str(last["date"])[:10])
    except ValueError:
        return False
    if (date.today() - last_d).days > max_stale_days:
        return False
    for bar in bars[-min_bars:]:
        if bar.get("close") is None or bar.get("high") is None or bar.get("low") is None:
            return False
    return True


def trim_bars(bars: list[dict], cutoff_days: int) -> list[dict]:
    cutoff = (date.today() - timedelta(days=cutoff_days)).isoformat()
    return [b for b in bars if str(b.get("date") or "") >= cutoff]


def load_free_bars(code: str) -> tuple[list[dict], dict]:
    """Sina and Tencent only. Does not call iFinD."""
    if code in _FREE:
        bars, meta = _FREE[code]
        return bars, dict(meta)
    meta = {
        "code": code,
        "sina_symbol": sina_symbol(code),
        "tencent_symbol": tencent_symbol(code),
        "sina_n": 0,
        "tencent_n": 0,
        "sina_error": "",
        "tencent_error": "",
        "source": "",
    }
    sina: list[dict] = []
    tencent: list[dict] = []
    try:
        sina = fetch_sina_daily(code)
        meta["sina_n"] = len(sina)
    except Exception as exc:
        meta["sina_error"] = str(exc)[:180]
    try:
        tencent = fetch_tencent_daily(code)
        meta["tencent_n"] = len(tencent)
    except Exception as exc:
        meta["tencent_error"] = str(exc)[:180]
    merged = merge_bars(sina, tencent)
    if sina and tencent:
        meta["source"] = "sina+tencent"
    elif sina:
        meta["source"] = "sina"
    elif tencent:
        meta["source"] = "tencent"
    meta["free_n"] = len(merged)
    if merged:
        meta["last"] = merged[-1]["date"]
    _FREE[code] = (merged, dict(meta))
    return merged, dict(meta)
