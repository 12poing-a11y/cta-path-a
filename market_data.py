# -*- coding: utf-8 -*-
"""Futures daily bars: Sina and Tencent first; Fuyao/TqSdk/iFinD fill gaps.

Exact delivery-month bars never fall back to continuous (*0 / CF00).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MEM: dict[str, list] = {}
_FREE: dict[str, tuple] = {}
_EXACT: dict[str, tuple] = {}

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


def valid_bar_asof(bar: dict, max_date: date) -> bool:
    """True only for dated, plausible OHLC bars no later than max_date."""
    try:
        day = date.fromisoformat(str(bar.get("date") or "")[:10])
        high = float(bar.get("high"))
        low = float(bar.get("low"))
        close = float(bar.get("close"))
    except (TypeError, ValueError):
        return False
    return day <= max_date and low > 0 and close > 0 and low <= close <= high and high / low <= 5


def filter_bars_asof(bars: list[dict], max_date: date | None = None) -> list[dict]:
    """Drop future-dated and malformed OHLC bars using the closed-session cap."""
    cap = max_date or latest_expected_session_date()
    return [bar for bar in bars if valid_bar_asof(bar, cap)]


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


def latest_expected_session_date(now: datetime | None = None) -> date:
    """Latest weekday day-session date expected to be closed (15:00 Asia/Shanghai).

    Weekday-only calendar: exchange holidays are not modelled. On holidays the
    fallback may be attempted, but the actual last bar is retained and reported.
    """
    local = (now or datetime.now(TZ_SHANGHAI)).astimezone(TZ_SHANGHAI)
    day = local.date()
    if local.weekday() >= 5 or local.time() < time(15, 0):
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def save_chart_history(code: str, bars: list[dict], root: Path | None = None) -> Path | None:
    """Persist merged free+iFinD daily history for the local chart reader."""
    code = str(code or "").upper()
    if not code or not bars:
        return None
    root = Path(root or ROOT)
    path = root / ".cache" / "history" / f"{code}0.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cap = latest_expected_session_date().isoformat()
        valid_bars = [row for row in bars if str(row.get("date") or "") <= cap]
        prior = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        if not isinstance(prior, list):
            prior = []
        # Purge previously persisted future-dated rows instead of carrying them
        # forward forever when the cache is refreshed.
        prior = [row for row in prior if isinstance(row, dict) and str(row.get("date") or "") <= cap]
        merged = merge_bars(valid_bars, prior)
        path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
        return path
    except (OSError, json.JSONDecodeError):
        return None


def series_sufficient(
    bars: list[dict],
    min_bars: int,
    max_stale_days: int = 12,
    expected_date: date | str | None = None,
) -> bool:
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
    if expected_date is not None:
        try:
            expected = expected_date if isinstance(expected_date, date) else date.fromisoformat(str(expected_date)[:10])
        except ValueError:
            return False
        if last_d < expected:
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
    merged = filter_bars_asof(merge_bars(sina, tencent))
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


def fetch_sina_exact_contract(contract: str, timeout: float = 20) -> list[dict]:
    """Sina/AkShare daily for a delivery month (e.g. CF2701). Not continuous."""
    contract = str(contract or "").upper()
    if not contract or contract.endswith("0") and len(contract) <= 3:
        return []
    # Reuse the same Sina daily endpoint used for continuous symbols.
    return filter_bars_asof(fetch_sina_symbol(contract, timeout=timeout))


def fill_exact_contract_with_fuyao(
    contract: str,
    bars: list[dict],
    *,
    need_date: str | date | None = None,
    root: Path | None = None,
) -> tuple[list[dict], dict]:
    """Gap-fill exact-contract series via Fuyao. Never substitutes continuous.

    If ``need_date`` is set and already present, returns bars unchanged without
    calling the network. Otherwise merges Fuyao bars under existing dates.
    """
    meta = {
        "contract": str(contract).upper(),
        "fuyao": False,
        "fuyao_n": 0,
        "fuyao_error": "",
        "thscode": None,
        "need_date": None,
    }
    need = None
    if need_date is not None:
        need = need_date.isoformat() if isinstance(need_date, date) else str(need_date)[:10]
        meta["need_date"] = need
        if any(str(b.get("date") or "")[:10] == need for b in bars):
            return bars, meta
    else:
        # No explicit target date: skip network if free series already covers the
        # latest closed session.
        expected = latest_expected_session_date().isoformat()
        if bars and str(bars[-1].get("date") or "")[:10] >= expected:
            return bars, meta

    try:
        from fuyao_client import fetch_exact_contract_daily
    except ImportError as exc:
        meta["fuyao_error"] = f"import:{exc}"
        return bars, meta

    fuyao_bars, fmeta = fetch_exact_contract_daily(contract, root=root)
    meta["thscode"] = fmeta.get("thscode")
    meta["fuyao_error"] = fmeta.get("error") or ""
    if not fuyao_bars:
        return bars, meta

    # Primary = existing (Sina); secondary = Fuyao fills holes only.
    merged = filter_bars_asof(merge_bars(bars, fuyao_bars))
    meta["fuyao"] = True
    meta["fuyao_n"] = len(fuyao_bars)
    if need and not any(str(b.get("date") or "")[:10] == need for b in merged):
        meta["fuyao_error"] = meta["fuyao_error"] or f"missing_need_date:{need}"
    return merged, meta


def fill_exact_contract_with_tqsdk(
    contract: str,
    bars: list[dict],
    *,
    need_date: str | date | None = None,
    root: Path | None = None,
    length: int = 400,
) -> tuple[list[dict], dict]:
    """Gap-fill exact-contract series via TqSdk. Never substitutes continuous.

    Soft-skips when TQ_USER/TQ_PASS (or .env.tqsdk) is missing. Existing dates
    win over TqSdk on merge; TqSdk only fills holes / extends history.
    """
    meta = {
        "contract": str(contract).upper(),
        "tqsdk": False,
        "tqsdk_n": 0,
        "tqsdk_error": "",
        "tqsdk_source": "",
        "need_date": None,
    }
    need = None
    if need_date is not None:
        need = need_date.isoformat() if isinstance(need_date, date) else str(need_date)[:10]
        meta["need_date"] = need
        if any(str(b.get("date") or "")[:10] == need for b in bars):
            return bars, meta
    else:
        expected = latest_expected_session_date().isoformat()
        if bars and str(bars[-1].get("date") or "")[:10] >= expected:
            return bars, meta

    try:
        from tqsdk_client import fetch_daily_bars, load_credentials
    except ImportError as exc:
        meta["tqsdk_error"] = f"import:{exc}"
        return bars, meta

    if not load_credentials(root=root):
        meta["tqsdk_error"] = "no-auth"
        return bars, meta

    tq_bars, src = fetch_daily_bars(contract, length=length, main=False, root=root)
    meta["tqsdk_source"] = src
    if not tq_bars:
        meta["tqsdk_error"] = src or "empty"
        return bars, meta

    merged = filter_bars_asof(merge_bars(bars, tq_bars))
    meta["tqsdk"] = True
    meta["tqsdk_n"] = len(tq_bars)
    if need and not any(str(b.get("date") or "")[:10] == need for b in merged):
        meta["tqsdk_error"] = meta["tqsdk_error"] or f"missing_need_date:{need}"
    return merged, meta


def load_exact_contract_bars(
    contract: str,
    *,
    need_date: str | date | None = None,
    root: Path | None = None,
    use_cache: bool = True,
) -> tuple[list[dict], dict]:
    """Sina exact-contract daily; Fuyao then TqSdk gap-fill. Continuous rejected."""
    contract = str(contract or "").upper()
    meta: dict = {
        "contract": contract,
        "source": "",
        "sina_n": 0,
        "fuyao": False,
        "fuyao_n": 0,
        "tqsdk": False,
        "tqsdk_n": 0,
        "error": "",
    }
    if not contract:
        meta["error"] = "empty_contract"
        return [], meta
    # Reject obvious continuous symbols (CF0 / MA0), keep CF2701.
    if re_fullmatch_continuous(contract):
        meta["error"] = "continuous_forbidden"
        return [], meta

    cache_key = f"{contract}|{need_date}"
    if use_cache and cache_key in _EXACT:
        bars, cached = _EXACT[cache_key]
        return bars, dict(cached)

    sina: list[dict] = []
    try:
        sina = fetch_sina_exact_contract(contract)
        meta["sina_n"] = len(sina)
    except Exception as exc:  # noqa: BLE001
        meta["error"] = f"sina:{exc}"[:180]

    bars, fmeta = fill_exact_contract_with_fuyao(
        contract, sina, need_date=need_date, root=root
    )
    meta.update(
        {
            "fuyao": bool(fmeta.get("fuyao")),
            "fuyao_n": int(fmeta.get("fuyao_n") or 0),
            "thscode": fmeta.get("thscode"),
            "fuyao_error": fmeta.get("fuyao_error") or "",
            "need_date": fmeta.get("need_date"),
        }
    )

    bars, tmeta = fill_exact_contract_with_tqsdk(
        contract, bars, need_date=need_date, root=root
    )
    meta.update(
        {
            "tqsdk": bool(tmeta.get("tqsdk")),
            "tqsdk_n": int(tmeta.get("tqsdk_n") or 0),
            "tqsdk_error": tmeta.get("tqsdk_error") or "",
            "tqsdk_source": tmeta.get("tqsdk_source") or "",
        }
    )
    if not meta.get("need_date") and tmeta.get("need_date"):
        meta["need_date"] = tmeta.get("need_date")

    parts = []
    if sina:
        parts.append("sina")
    if meta["fuyao"]:
        parts.append("fuyao")
    if meta["tqsdk"]:
        parts.append("tqsdk")
    meta["source"] = "+".join(parts) if parts else ""
    if bars:
        meta["last"] = bars[-1]["date"]
        meta["n"] = len(bars)
    if use_cache:
        _EXACT[cache_key] = (bars, dict(meta))
    return bars, dict(meta)


def re_fullmatch_continuous(contract: str) -> bool:
    """True for variety continuous codes like CF0 / RB0 (not CF2701)."""
    return bool(re.fullmatch(r"[A-Z]+0", str(contract or "").upper()))
