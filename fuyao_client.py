# -*- coding: utf-8 -*-
"""Tonghuashun Fuyao REST client — exact-contract daily bars only.

Key from FUYAO_API_KEY / API_KEY env, or repo-local .env.fuyao (gitignored).
CZCE delivery months use 3-digit YMM tickers (CF2701 -> CF701.CZC).
Never returns continuous (CF00) when asked for a delivery month.

Options note: Fuyao option daily bars expose OHLC/volume/turnover only — no IV
and no OI. Do not use this client as the Gamma Wall option-chain source.
Missing API key must soft-fail (empty bars) so GitHub daily jobs never break.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASE = "https://fuyao.aicubes.cn"
TZ_SH = ZoneInfo("Asia/Shanghai")

# Products we map today. Suffix is Fuyao exchange tag on thscode.
CZCE_PRODUCTS = {
    "CF",
    "SR",
    "MA",
    "TA",
    "SA",
    "RM",
    "OI",
    "FG",
    "PF",
    "SH",
    "UR",
    "AP",
    "CJ",
    "PK",
    "PX",
    "SM",
    "SF",
    "ZC",
}
SHFE_PRODUCTS = {"CU", "AL", "ZN", "PB", "NI", "SN", "AU", "AG", "RB", "HC", "SS", "BU", "RU", "SP", "AO", "BR"}
DCE_PRODUCTS = {"A", "B", "M", "Y", "P", "C", "CS", "JD", "L", "V", "PP", "J", "JM", "I", "EG", "EB", "PG", "LH"}
INE_PRODUCTS = {"SC", "NR", "LU", "BC"}
CFE_PRODUCTS = {"IF", "IH", "IC", "IM", "T", "TF", "TS", "TL"}


def load_api_key(*, root: Path | None = None) -> str | None:
    key = (os.environ.get("FUYAO_API_KEY") or os.environ.get("API_KEY") or "").strip()
    if key:
        return key
    base = Path(root or ROOT)
    for name in (".env.fuyao", ".env"):
        path = base / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() in {"FUYAO_API_KEY", "API_KEY"} and v.strip():
                return v.strip().strip('"').strip("'")
    return None


def czce_delivery_ticker(contract: str) -> str:
    """CF2701 -> CF701 (Zhengzhou one-digit year)."""
    m = re.fullmatch(r"([A-Za-z]+)(\d{4})", str(contract or "").strip())
    if not m:
        raise ValueError(f"合约须为品种+四位年月，例如 CF2701，收到：{contract!r}")
    product, yymm = m.group(1).upper(), m.group(2)
    return f"{product}{int(yymm[:2]) % 10}{yymm[2:]}"


def to_thscode(contract: str) -> str:
    """Map internal delivery-month code to Fuyao thscode. Rejects continuous *0."""
    raw = str(contract or "").strip().upper()
    if not raw:
        raise ValueError("空合约代码")
    if raw.endswith("0") and not re.search(r"\d{3,4}$", raw):
        # MA0 / CF0 style continuous — not allowed as exact-contract substitute.
        raise ValueError(f"禁止把主连 {raw} 当作单合约 thscode")
    if "." in raw:
        # Already a thscode; still reject continuous tickers.
        ticker = raw.split(".", 1)[0]
        if re.fullmatch(r"[A-Z]+00", ticker):
            raise ValueError(f"禁止主连 thscode：{raw}")
        return raw

    m = re.fullmatch(r"([A-Z]+)(\d{3,4})", raw)
    if not m:
        raise ValueError(f"无法解析合约：{contract!r}")
    product, digits = m.group(1), m.group(2)
    if product in CZCE_PRODUCTS:
        ticker = czce_delivery_ticker(f"{product}{digits}") if len(digits) == 4 else f"{product}{digits}"
        return f"{ticker}.CZC"
    if product in SHFE_PRODUCTS:
        if len(digits) != 4:
            raise ValueError(f"上期所合约须四位年月：{contract}")
        return f"{product}{digits}.SHF"
    if product in DCE_PRODUCTS:
        if len(digits) != 4:
            raise ValueError(f"大商所合约须四位年月：{contract}")
        return f"{product}{digits}.DCE"
    if product in INE_PRODUCTS:
        if len(digits) != 4:
            raise ValueError(f"上期能源合约须四位年月：{contract}")
        return f"{product}{digits}.INE"
    if product in CFE_PRODUCTS:
        if len(digits) != 4:
            raise ValueError(f"中金所合约须四位年月：{contract}")
        return f"{product}{digits}.CFE"
    raise ValueError(f"暂未映射交易所后缀的品种：{product}")


def _ms_to_iso(ms: Any) -> str | None:
    try:
        ts = int(ms)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    # Fuyao uses millisecond unix timestamps.
    if ts < 10_000_000_000:
        ts *= 1000
    day = datetime.fromtimestamp(ts / 1000.0, tz=TZ_SH).date()
    return day.isoformat()


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if x == x else None  # noqa: PLR0124 NaN check
    except (TypeError, ValueError):
        return None


def bars_from_daily_payload(data: dict[str, Any] | None) -> list[dict]:
    """Normalize Fuyao daily K payload to market_data-style bars."""
    if not isinstance(data, dict):
        return []
    out: list[dict] = []
    for row in data.get("item") or []:
        if not isinstance(row, dict):
            continue
        d = _ms_to_iso(row.get("timestamp"))
        close = _f(row.get("close_price"))
        if not d or close is None or close <= 0:
            continue
        open_ = _f(row.get("open_price"))
        high = _f(row.get("high_price"))
        low = _f(row.get("low_price"))
        if high is None:
            high = close
        if low is None:
            low = close
        if open_ is None:
            open_ = close
        if low <= 0 or high < low or high / low > 5:
            continue
        out.append(
            {
                "date": d,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": _f(row.get("volume")),
                "open_interest": _f(row.get("open_interest")),
                "hold": _f(row.get("open_interest")),
                "settle": _f(row.get("settle_price")) or close,
                "source": "fuyao",
            }
        )
    out.sort(key=lambda b: b["date"])
    return out


def api_get(path: str, *, key: str, timeout: float = 30, **params: Any) -> dict[str, Any]:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers={"X-api-key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"code": e.code, "message": raw[:300], "data": None}
        if "code" not in body:
            body = {"code": e.code, "message": str(body), "data": None}
        return body


def fetch_exact_contract_daily(
    contract: str,
    *,
    root: Path | None = None,
    key: str | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Fetch exact delivery-month daily bars. Never substitutes continuous."""
    meta: dict[str, Any] = {
        "contract": str(contract).upper(),
        "thscode": None,
        "source": "",
        "error": "",
        "n": 0,
    }
    api_key = key if key is not None else load_api_key(root=root)
    if not api_key:
        meta["error"] = "no_api_key"
        return [], meta
    try:
        thscode = to_thscode(contract)
    except ValueError as exc:
        meta["error"] = str(exc)
        return [], meta
    meta["thscode"] = thscode
    params: dict[str, Any] = {"thscode": thscode}
    if start_ms is not None and end_ms is not None:
        params["start"] = int(start_ms)
        params["end"] = int(end_ms)
    body = api_get("/api/futures/prices/daily", key=api_key, **params)
    if body.get("code") != 0:
        meta["error"] = f"code={body.get('code')} {body.get('message')}"
        return [], meta
    bars = bars_from_daily_payload(body.get("data") if isinstance(body.get("data"), dict) else None)
    meta["n"] = len(bars)
    meta["source"] = "fuyao"
    if bars:
        meta["last"] = bars[-1]["date"]
        meta["first"] = bars[0]["date"]
    return bars, meta


def has_date(bars: list[dict], asof: str) -> bool:
    target = str(asof)[:10]
    return any(str(b.get("date") or "")[:10] == target for b in bars)
